"""Local ELT: independently runnable raw collector and offline processor."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from etl_runtime import Runtime,atomic_json
PROJECT=Path(__file__).resolve().parents[2];BACKEND=PROJECT/'backend';ROOT=BACKEND/'data/operations'
sys.path.insert(0,str(BACKEND))


def count_texts():
    path=ROOT/'tjdft-documents/documents.json'
    return len(json.loads(path.read_text(encoding='utf8'))) if path.exists() else 0

def inputs_signature(sources=None):
    sources=set(sources or ('tjdft','ementas','djen','doctrine','pangea'))
    mapping={'tjdft':('tjdft-documents/documents.json',), 'ementas':('jurisprudence-ementas/queue.json',),
             'djen':('djen-documents/queue.json',),'doctrine':('doctrine/manifest.json',),
             'pangea':('pangea-raw/manifest.json','pangea-raw/all-pages.json')}
    digest=hashlib.sha256();artifacts=set()
    for source in sorted(sources):
        for relative in mapping[source]:
            path=ROOT/relative
            if not path.exists():continue
            value=json.loads(path.read_text(encoding='utf8'))
            if source=='doctrine':value={key:value.get(key,{}) for key in ('documents','pending','rejected')}
            if source=='pangea' and relative.endswith('manifest.json'):value={k:v for k,v in value.items() if k not in ('started_at','finished_at')}
            digest.update(json.dumps(value,sort_keys=True).encode())
            if source in ('tjdft','ementas','djen'):
                for row in value.values() if isinstance(value,dict) else value:
                    if isinstance(row,dict) and row.get('artifact_path'):artifacts.add(row['artifact_path'])
    for relative in sorted(artifacts):
        path=(ROOT/relative).resolve()
        if not path.is_relative_to(ROOT.resolve()):raise ValueError('Artifact outside local corpus')
        stat=path.stat() if path.exists() else None
        digest.update(json.dumps([relative,stat.st_size if stat else None,stat.st_mtime_ns if stat else None]).encode())
    for path in sorted((BACKEND/'src/nlp').glob('*.py')):digest.update(path.read_bytes())
    digest.update((BACKEND/'src/nlp/prompt.txt').read_bytes())
    return digest.hexdigest()


def collect(runtime,args):
    tools=Path(__file__).parent
    steps=[]
    if 'doctrine' in args.sources:steps.append(('collect_doctrine',[str(PROJECT/'tools/doctrine/collect_doctrine_raw.py'),'--limit',str(args.doctrine_limit)]))
    if 'pangea' in args.sources:steps.append(('collect_pangea',[str(tools/'collect_pangea_raw.py')]))
    if 'tjdft' in args.sources and count_texts()<args.target:
        steps.append(('collect_tjdft',[str(tools/'collect_tjdft_texts.py'),'--limit',str(args.batch_size),'--target',str(args.target)]))
    if 'ementas' in args.sources:steps.append(('collect_ementas',[str(tools/'collect_ementas.py'),'--limit','400']))
    if 'djen' in args.sources:steps.append(('collect_djen',[str(tools/'collect_multicourt_publications.py'),'--limit','1000']))
    codes=[runtime.run(name,command) for name,command in steps]
    runtime.publish(stored_unique_tjdft=count_texts())
    atomic_json(ROOT/'collection-target.json',{'target':args.target,'stored_unique':count_texts(),
        'count_basis':'unique_TJDFT_full_text_UUIDs','status':'target_reached' if count_texts()>=args.target else 'collecting',
        'processing_status':'separate_ELT_worker','elt_job_id':runtime.id})
    return codes

def process(runtime,args):
    tools=Path(__file__).parent;codes=[]
    for name,relative,command in [
        ('import_doctrine','doctrine/manifest.json',[str(PROJECT/'tools/doctrine/import_doctrine_local.py')]),
        ('import_pangea','pangea-raw/manifest.json',['manage.py','import_pangea_raw'])]:
        source='doctrine' if name=='import_doctrine' else 'pangea'
        if source in args.sources and (ROOT/relative).exists():codes.append(runtime.run(name,command))
    has_jurisprudence=bool(set(args.sources)&{'tjdft','ementas','djen'})
    if has_jurisprudence:codes.append(runtime.run('index_acquired',['manage.py','index_jurisprudence_queues']))
    juris_signature=inputs_signature(('tjdft','ementas','djen')) if has_jurisprudence else None
    if has_jurisprudence and runtime.state.get('nlp_completed_signature')!=juris_signature and any((ROOT/path).exists() for path in ('tjdft-documents/documents.json','jurisprudence-ementas/queue.json','djen-documents/queue.json')):
        # Every processing cycle has an immutable, separate queue and output pointer.
        import uuid
        job=str(uuid.uuid4());runtime.publish(nlp_job_id=job)
        code=runtime.run('nlp',[str(tools/'run_nlp_local.py'),'--job-id',job]);codes.append(code)
        if code==0:
            codes.append(runtime.run('import_nlp',[str(tools/'import_local_results.py'),'--job-id',job]))
            codes.append(runtime.run('coverage',[str(tools/'report_coverage.py')]))
            if not any(codes[-3:]):runtime.publish(nlp_completed_signature=juris_signature)
    return codes

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['collect','process','all'],default='all')
    parser.add_argument('--sources',default='doctrine,pangea,tjdft,ementas,djen')
    parser.add_argument('--target',type=int,default=20000);parser.add_argument('--batch-size',type=int,default=1000)
    parser.add_argument('--doctrine-limit',type=int,default=50);parser.add_argument('--once',action='store_true');parser.add_argument('--follow',action='store_true')
    args=parser.parse_args(argv);args.sources=tuple(dict.fromkeys(args.sources.split(',')))
    if set(args.sources)-{'doctrine','pangea','tjdft','ementas','djen'} or not args.sources:parser.error('Unknown source')
    if args.target<1 or not 25<=args.batch_size<=1000 or args.batch_size%25 or not 1<=args.doctrine_limit<=100:parser.error('Invalid bounded batch options')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
    import django;django.setup()
    from django.conf import settings
    config=settings.DATABASES['default']
    if config['ENGINE']!='django.db.backends.sqlite3' and config.get('HOST') not in ('localhost','127.0.0.1','::1'):
        raise ValueError('Local database required')
    with Runtime(BACKEND,args.mode) as runtime:
        runtime.publish(sources=list(args.sources),target=args.target,batch_size=args.batch_size)
        failures=stagnant=0;last_signature=None
        while True:
            before=count_texts();codes=[]
            reached_before_processing=False
            if args.mode=='collect' and not args.once and 'tjdft' in args.sources and before>=args.target:
                runtime.finish('completed');return 0
            reached_before_processing=args.mode=='all' and not args.once and 'tjdft' in args.sources and before>=args.target
            if args.mode in ('collect','all') and not reached_before_processing:codes.extend(collect(runtime,args))
            if args.mode in ('process','all'):
                signature=inputs_signature(args.sources)
                if signature!=last_signature or args.once:
                    processed=process(runtime,args);codes.extend(processed)
                    if not any(processed):
                        last_signature=signature;runtime.publish(last_processed_signature=signature)
                else:runtime.publish(phase='waiting_for_archived_inputs')
            failures=failures+1 if any(codes) else 0
            tf_steps=[step for step in runtime.state['steps'] if step['name']=='collect_tjdft']
            stagnant=stagnant+1 if args.mode!='process' and tf_steps and tf_steps[-1]['exit_code']==0 and count_texts()==before else 0
            if failures>=3:
                runtime.finish('failed_after_retries');return 1
            if args.mode=='process':
                collector_path=ROOT/'etl-collect.json'
                collector=json.loads(collector_path.read_text(encoding='utf8')) if collector_path.exists() else {}
                if args.once or not args.follow or collector.get('status')!='running':
                    # Catch final pages published while the last snapshot was processing.
                    if args.follow and inputs_signature(args.sources)!=last_signature and not any(codes):continue
                    runtime.finish('partial_failure' if any(codes) else 'completed');return int(any(codes))
            elif args.once or 'tjdft' not in args.sources or count_texts()>=args.target or stagnant>=2:
                runtime.finish('partial_failure' if any(codes) else 'source_exhausted' if stagnant>=2 and count_texts()<args.target else 'completed')
                return int(any(codes) or runtime.state['status']=='source_exhausted')
            time.sleep(10 if args.mode=='process' and not any(codes) else 30 if any(codes) else .3)

if __name__=='__main__':raise SystemExit(main())
