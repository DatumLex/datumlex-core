"""Archive public Pangea responses before any normalization/database import."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from datetime import datetime,timezone
PROJECT=Path(__file__).resolve().parents[2];BACKEND=PROJECT/'backend'
sys.path.insert(0,str(BACKEND))

def save(path,value):
    from etl_runtime import atomic_json
    atomic_json(path,value)


def collect_main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--max-pages',type=int,default=10)
    parser.add_argument('--query',default='responsabilidade civil');parser.add_argument('--courts')
    parser.add_argument('--page-size',type=int,default=100);parser.add_argument('--start-page',type=int)
    args=parser.parse_args()
    if not 1<=args.max_pages<=100 or not 1<=args.page_size<=100 or args.start_page is not None and args.start_page<0:parser.error('Invalid bounded pagination')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
    import django;django.setup()
    from src.api.pangea_client import PangeaPublicSearchClient
    from src.db.court_catalog import ACTIVE_COURTS
    from src.api.pangea_scope import selected_courts
    courts=selected_courts(args.courts or ACTIVE_COURTS)
    root=BACKEND/'data/operations/pangea-raw';pages=root/'pages';pages.mkdir(parents=True,exist_ok=True)
    client=PangeaPublicSearchClient();catalog=client.get_catalog()
    catalog_raw=json.dumps(catalog,ensure_ascii=False,sort_keys=True).encode();catalog_sha=hashlib.sha256(catalog_raw).hexdigest()
    catalog_path=root/('catalog-'+catalog_sha+'.json')
    from etl_runtime import archive_bytes
    archive_bytes(catalog_path,catalog_raw)
    index_path=root/'all-pages.json'
    index=json.loads(index_path.read_text(encoding='utf8')) if index_path.exists() else {'pages':[]}
    known={item.get('receipt_key',item['sha256']) for item in index['pages']}
    cursor_path=root/'cursor.json'
    cursor=json.loads(cursor_path.read_text(encoding='utf8')) if cursor_path.exists() else {'next_page':0,'exhausted':False}
    scope={'query':args.query,'courts':list(courts),'page_size':args.page_size}
    if cursor.get('scope')!=scope:cursor={'next_page':0,'exhausted':False}
    start=args.start_page if args.start_page is not None else 0 if cursor.get('exhausted') else cursor['next_page']
    report={**scope,
            'catalog_version':str(catalog.get('versao','')),'catalog_path':catalog_path.name,'catalog_sha256':catalog_sha,
            'started_at':datetime.now(timezone.utc).isoformat(),'status':'running','pages':[]}
    save(root/'manifest.json',report)
    try:
        for page in range(start,start+args.max_pages):
            payload=client.search_page(report['query'],page,args.page_size,courts=courts)
            raw=client.last_response_bytes
            if not isinstance(raw,bytes):raise ValueError('Missing original HTTP response bytes')
            sha=hashlib.sha256(raw).hexdigest()
            artifact=pages/(sha+'.json')
            from etl_runtime import archive_bytes
            archive_bytes(artifact,raw)
            entry={'page':page,'path':str(artifact.relative_to(root)),'sha256':sha}
            report['pages'].append(entry)
            receipt=hashlib.sha256(json.dumps({'scope':scope,'page':page,'sha':sha,'catalog':catalog_sha},sort_keys=True).encode()).hexdigest()
            if receipt not in known:
                index['pages'].append({**entry,'receipt_key':receipt,'query':report['query'],'courts':report['courts'],
                    'catalog_version':report['catalog_version'],'catalog_path':report['catalog_path'],
                    'catalog_sha256':report['catalog_sha256'],
                    'source_complete':not payload['resultados'] or (page+1)*args.page_size>=payload['total']})
                known.add(receipt)
            save(index_path,index)
            report['source_total']=payload['total'];report['status']='partial'
            # Commit archived response + manifest before advancing its cursor.
            save(root/'manifest.json',report)
            cursor={'scope':scope,'next_page':page+1,'exhausted':not payload['resultados'] or (page+1)*args.page_size>=payload['total']}
            save(cursor_path,cursor)
            print(json.dumps({'source':'pangea','page':page,'archived':len(payload['resultados'])}),flush=True)
            if cursor['exhausted']:
                report['status']='completed';break
    except Exception as exc:
        report['status']='failed' if not report['pages'] else 'partial_failure';report['error_type']=type(exc).__name__;save(root/'manifest.json',report);raise
    report['finished_at']=datetime.now(timezone.utc).isoformat();save(root/'manifest.json',report)
    return 0

def main():
    from etl_runtime import file_lock
    with file_lock(BACKEND/'data/operations/pangea-raw/source.lock'):
        return collect_main()

if __name__=='__main__':raise SystemExit(main())
