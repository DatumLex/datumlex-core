"""Recover/collect DataJud history and process only available, unprocessed texts.

Default: read-only plan. --gravar enables writes. Remote collection is opt-in.
Uses the project's canonical courts, subjects, normalizer, loader and NLP.
"""
import argparse
from collections import Counter
from contextlib import ExitStack
from datetime import date, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import NAMESPACE_URL, uuid4, uuid5

LOCKS = ExitStack()


def normalize_backup(row, start, end, subject_codes):
    from src.etl.transformer import normalize
    scope = {
        'court': row['court'], 'start': start.isoformat(), 'end': end.isoformat(),
        'end_exclusive': (end + timedelta(days=1)).isoformat(),
        'subject_codes': subject_codes,
    }
    if row['source_scope'].get('origin') != 'datajud':
        raise ValueError('source_is_not_a_recorded_datajud_collection')
    original_id = row['source_id']
    if row['court'] != 'TJDFT':
        original_id = original_id.removeprefix(row['court'] + ':')
    record = normalize({'_id': original_id, '_source': row['raw_payload']}, scope)
    if record['source_id'] != row['source_id']:
        raise ValueError('source_identity_changed_by_normalization')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--projeto', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--inicio', type=date.fromisoformat, default=date(2016, 1, 1))
    parser.add_argument('--fim', type=date.fromisoformat, help='Default: today in America/Sao_Paulo')
    parser.add_argument('--banco-origem', default='datumlex_backup_review_20261113')
    parser.add_argument('--sem-backup', action='store_true')
    parser.add_argument('--tribunais', help='Default: the ten ACTIVE_COURTS of the project')
    parser.add_argument('--gravar', action='store_true')
    parser.add_argument('--coletar', action='store_true', help='Also query the public DataJud API')
    parser.add_argument('--paginas', type=int, default=20, help='Bound per court and invocation')
    parser.add_argument('--tamanho-pagina', type=int, default=100)
    parser.add_argument('--limite-recuperacao', type=int, default=0, help='0: all eligible backup records')
    parser.add_argument('--nlp', action='store_true')
    parser.add_argument('--raiz-textos', type=Path, help='Original archive root; default backend/data/operations')
    parser.add_argument('--limite-nlp', type=int, default=100)
    args = parser.parse_args()
    project = args.projeto.resolve()
    backend = project / 'backend'
    # A queued annual job can be cancelled without interrupting another year.
    if args.coletar and args.fim and args.inicio.year == args.fim.year:
        cancellation = backend / 'data/operations' / f'datajud-skip-year-{args.inicio.year}.flag'
        if cancellation.exists():
            print(f'Ano {args.inicio.year} retirado da fila por solicitação do usuário. '
                  f'Para reativar, remova {cancellation}', flush=True)
            return 0
    sys.path.insert(0, str(backend))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.conf import settings
    from django.core.management import call_command
    from django.db import transaction
    from django.db.models import Exists, OuterRef, Subquery
    from django.utils import timezone
    import psycopg
    from psycopg.rows import dict_row
    from src.db.court_catalog import ACTIVE_COURTS
    from src.db.subject_catalog import DEFAULT_DATAJUD_SUBJECT_CODES
    from src.db.models import ExtractionRun, FactProcess, NlpExtraction, NlpTextVersion
    from src.etl.loader import load_record
    from src.nlp.adapters import read_source
    from src.nlp.topics import TOPICS
    from src.services.nlp_evidence import persist_result
    from src.services.period import today
    end = args.fim or today()
    if not date(2016, 1, 1) <= args.inicio <= end <= today():
        parser.error('Use a period from 2016-01-01 through today.')
    if not 1 <= args.paginas <= 100 or not 1 <= args.tamanho_pagina <= 1000:
        parser.error('Use 1..100 pages and 1..1000 records per page.')
    if args.limite_recuperacao < 0 or not 1 <= args.limite_nlp <= 1000:
        parser.error('Recovery limit must be >=0; NLP limit must be 1..1000.')
    courts = list(ACTIVE_COURTS) if not args.tribunais else args.tribunais.split(',')
    if not courts or len(courts) != len(set(courts)) or set(courts) - set(ACTIVE_COURTS):
        parser.error('Unknown or repeated court.')
    config = settings.DATABASES['default']
    if config['ENGINE'] != 'django.db.backends.postgresql' or config.get('HOST') not in ('localhost', '127.0.0.1', '::1'):
        raise RuntimeError('Only the configured local PostgreSQL target is allowed.')
    if args.banco_origem == config['NAME'] and not args.sem_backup:
        raise RuntimeError('Source and target databases must differ.')
    subjects = list(DEFAULT_DATAJUD_SUBJECT_CODES)
    report = {
        'inicio': args.inicio.isoformat(), 'fim': end.isoformat(), 'banco_destino': config['NAME'],
        'tribunais': courts, 'temas_nlp': [{'id': key, 'nome': label} for key, label, _ in TOPICS],
        'periodo_datajud': 'dataAjuizamento', 'simulacao': not args.gravar,
        'recuperacao': {}, 'coleta': {}, 'nlp': {},
    }
    state = None
    if args.gravar:
        sys.path.insert(0, str(project / 'tools/nlp_validation'))
        from etl_runtime import file_lock
        operations = backend / 'data/operations'
        operations.mkdir(parents=True, exist_ok=True)
        LOCKS.enter_context(file_lock(operations / 'etl-process.lock'))
        if args.coletar:
            LOCKS.enter_context(file_lock(operations / 'etl-collect.lock'))
        state = backend / 'data/operations/manual-datajud' / str(uuid4())
        state.mkdir(parents=True)
    def save():
        if state:
            temporary = state / 'report.json.part'
            temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf8')
            temporary.replace(state / 'report.json')
    def say(message):
        print(message, flush=True)
    # The source connection is read-only. Destination rows use the official loader.
    if not args.sem_backup:
        connection = psycopg.connect(host=config['HOST'], port=config['PORT'], user=config['USER'],
            password=config['PASSWORD'], dbname=args.banco_origem, connect_timeout=10, row_factory=dict_row)
        connection.read_only = True
        try:
            with connection.cursor() as cursor:
                cursor.execute('''SELECT f.court, t.year, count(*) AS registros
                    FROM fact_resource f JOIN dim_time t ON t.id_time=f.id_time
                    WHERE f.court=ANY(%s) AND t.data BETWEEN %s AND %s
                    GROUP BY f.court,t.year ORDER BY f.court,t.year''', (courts,args.inicio,end))
                report['backup_por_ano_tribunal'] = cursor.fetchall()
            if args.gravar:
                existing = set(FactProcess.objects.values_list('source_id', flat=True))
                runs = {}
                counters = {court: Counter() for court in courts}
                with connection.cursor(name='datumlex_manual_recovery') as cursor:
                    cursor.itersize = 200
                    cursor.execute('''SELECT f.id_resource,f.source_id,f.court,f.raw_payload,
                        r.scope AS source_scope,r.status AS source_run_status,r.id AS source_run_id
                        FROM fact_resource f JOIN dim_time t ON t.id_time=f.id_time
                        JOIN extraction_run r ON r.id=f.last_run_id
                        WHERE f.court=ANY(%s) AND t.data BETWEEN %s AND %s
                        ORDER BY f.id_resource''', (courts,args.inicio,end))
                    loaded = 0
                    for row in cursor:
                        counts = counters[row['court']]
                        counts['lidos'] += 1
                        try:
                            record = normalize_backup(row, args.inicio, end, subjects)
                        except ValueError as exc:
                            counts['rejeitados'] += 1
                            with (state/'rejected.jsonl').open('a', encoding='utf8') as output:
                                output.write(json.dumps({'source_id':row['source_id'],'motivo':str(exc)})+'\n')
                            continue
                        if record['source_id'] in existing:
                            counts['existentes_ignorados'] += 1
                            continue
                        if row['court'] not in runs:
                            runs[row['court']] = ExtractionRun.objects.create(scope={
                                'origin':'datajud_backup_recovery','court':row['court'],
                                'source_database':args.banco_origem,'source_is_snapshot':True,
                                'recovery_limit':args.limite_recuperacao,
                                'coverage':'Only eligible archived records; not complete historical coverage',
                                'start':args.inicio.isoformat(),'end':end.isoformat(),
                                'subject_codes':subjects,'period_field':'dataAjuizamento',
                                'source_run_ids':[], 'source_run_statuses':[],
                            }, status='running')
                        run = runs[row['court']]
                        try:
                            with transaction.atomic():
                                action = load_record(record, run)
                                run.created += action == 'created'
                                run.updated += action == 'updated'
                                run.stale += action == 'stale'
                                run.fetched += 1
                                for field,value in [('source_run_ids',row['source_run_id']),('source_run_statuses',row['source_run_status'])]:
                                    if value not in run.scope[field]: run.scope[field].append(value)
                                run.save()
                        except Exception:
                            run.refresh_from_db();run.status='failed';run.error='Recovery interrupted; rerun skips saved IDs.'
                            run.finished_at=timezone.now();run.save();raise
                        existing.add(record['source_id']);counts[action] += 1;loaded += 1
                        if loaded % 100 == 0:
                            report['recuperacao'] = {k:dict(v) for k,v in counters.items()};save()
                            say(f'Recuperados {loaded} registros novos do backup.')
                        if args.limite_recuperacao and loaded >= args.limite_recuperacao: break
                for run in runs.values():
                    run.status='completed';run.finished_at=timezone.now();run.save()
                report['recuperacao']={k:dict(v) for k,v in counters.items()}
        finally:
            connection.close()
    if args.coletar:
        if not args.gravar:
            report['coleta']={'status':'planejada; requer --gravar','limite_paginas_por_tribunal':args.paginas}
        else:
            from src.api.datajud_client import DataJudClient
            probe_scope={'court':courts[0],'start':args.inicio.isoformat(),'end_exclusive':(end+timedelta(days=1)).isoformat(),
                         'subject_codes':subjects,'page_size':1}
            try:
                DataJudClient(settings.DATAJUD_API_KEY,court=courts[0],attempts=1).search(probe_scope)
            except Exception as exc:
                report['coleta']={'status':'fonte_indisponivel','erro':str(exc),'tribunais_pendentes':courts}
                say('DataJud indisponível. Dados recuperados foram preservados; coleta remota não iniciada.')
            else:
                for court in courts:
                    say(f'Coletando DataJud: {court}, {args.inicio} a {end}.')
                    try:
                        call_command('extract_datajud',court=court,start=args.inicio.isoformat(),end=end.isoformat(),
                            subjects=','.join(map(str,subjects)),page_size=args.tamanho_pagina,max_pages=args.paginas)
                        run=ExtractionRun.objects.filter(scope__origin='datajud',scope__court=court,
                            scope__start=args.inicio.isoformat(),scope__end=end.isoformat()).order_by('-pk').first()
                        report['coleta'][court]={'status':run.status,'run_id':run.pk,'created':run.created} if run else {'status':'sem_execucao'}
                    except Exception as exc:
                        report['coleta'][court]={'status':'falha','erro':str(exc)}
                    save()
    if args.nlp:
        root=(args.raiz_textos or backend/'data/operations').resolve()
        latest=NlpTextVersion.objects.filter(document_id=OuterRef('document_id')).order_by('-created_at','-pk')
        successful=NlpExtraction.objects.filter(text_version_id=OuterRef('pk'),status__in=['completed','partial'])
        versions=NlpTextVersion.objects.filter(pk=Subquery(latest.values('pk')[:1]),document__court__in=courts).annotate(
            processed=Exists(successful)).select_related('document').defer('text')
        queue=[];checks=Counter()
        for version in versions.iterator(chunk_size=200):
            checks['versoes_verificadas']+=1
            if version.processed:
                checks['nlp_existente_ignorado']+=1;continue
            source=version.source
            if source.get('text_sha256') != version.sha256:
                checks['versao_inconsistente']+=1;continue
            day=source.get('decision_date') or source.get('publication_date')
            if not day or not args.inicio.isoformat()<=str(day)[:10]<=end.isoformat():
                checks['sem_data_ou_fora_periodo']+=1;continue
            try: read_source(source,root)
            except (OSError,ValueError,KeyError): checks['original_indisponivel_ou_invalido']+=1;continue
            queue.append(source)
            if len(queue)>=args.limite_nlp: break
        report['nlp']={**dict(checks),'textos_novos_elegiveis':len(queue),
            'nota':'Metadados DataJud não são inteiro teor. Sem texto original verificado, não há extração de teses.'}
        if args.gravar and queue:
            queue_path=state/'queue.json';queue_path.write_text(json.dumps(queue,ensure_ascii=False,indent=2),encoding='utf8')
            result=subprocess.run([sys.executable,'-m','src.nlp','--root',str(root),'--queue',str(queue_path),
                '--output',str(state/'runs'),'--guide',str(backend/'src/nlp/prompt.txt'),
                '--allow-unreviewed-calibration'],cwd=backend,capture_output=True,text=True,encoding='utf8')
            (state/'nlp.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf8')
            if result.returncode: report['nlp']['status']='falha; ver nlp.log'
            else:
                directory=Path(json.loads(result.stdout)['output']);saved=0
                for path in (directory/'results').rglob('*.json'):
                    output=json.loads(path.read_text(encoding='utf8'))
                    if output['status'] not in ('completed','partial'): continue
                    text=read_source(output['source'],root)
                    persist_result(output,text,request_key=uuid5(NAMESPACE_URL,'datumlex-local:'+output['result_sha256']));saved+=1
                report['nlp']['gravados']=saved
    if args.gravar:
        report['total_datajud_no_destino']=FactProcess.objects.count()
        report['relatorio']=str(state/'report.json');save()
    print(json.dumps(report,ensure_ascii=False,indent=2,default=str),flush=True)
    failures=report['coleta'].get('status')=='fonte_indisponivel' or any(
        isinstance(v,dict) and v.get('status')=='falha' for v in report['coleta'].values())
    return 2 if failures or report['nlp'].get('status','').startswith('falha') else 0


if __name__=='__main__':
    with LOCKS:
        raise SystemExit(main())
