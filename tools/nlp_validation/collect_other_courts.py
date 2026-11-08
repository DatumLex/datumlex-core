"""Supplement the running TJDFT collector without racing its NLP/import writer."""
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime,timezone
PROJECT=Path(__file__).resolve().parents[2];BACKEND=PROJECT/'backend'
sys.path.insert(0,str(BACKEND))

def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
    import django
    django.setup()
    from django.conf import settings
    config=settings.DATABASES['default']
    if config['ENGINE']!='django.db.backends.sqlite3' and config.get('HOST') not in ('localhost','127.0.0.1','::1'):
        raise ValueError('Local database required')
    directory=BACKEND/'data/operations';directory.mkdir(parents=True,exist_ok=True)
    path=directory/'other-courts-collection.json'
    import msvcrt
    lock=(directory/'other-courts-collection.lock').open('a+b');lock.seek(0)
    try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        print('Supplementary collector already running.');return 1
    report={'started_at':datetime.now(timezone.utc).isoformat(),'status':'running','steps':[],
            'nlp_processing':'Picked up by the next active jurisprudence/NLP batch; no concurrent NLP writer started.'}
    def save():
        temporary=path.with_suffix('.part');temporary.write_text(json.dumps(report,indent=2),encoding='utf8');temporary.replace(path)
    try:
        for label,command in [
            ('pangea_ten_courts',[sys.executable,'manage.py','sync_pangea','--query','responsabilidade civil','--page-size','100','--max-pages','10']),
            ('stj_tst_ementas',[sys.executable,str(Path(__file__).with_name('collect_ementas.py')),'--limit','400']),
            ('djen_ten_courts',[sys.executable,str(Path(__file__).with_name('collect_multicourt_publications.py')),'--limit','1000','--days','30']),
            ('index_collected_sources',[sys.executable,'manage.py','index_jurisprudence_queues'])]:
            report['phase']=label;save()
            try:code=subprocess.run(command,cwd=BACKEND,timeout=3600).returncode
            except (OSError,subprocess.TimeoutExpired):code=1
            report['steps'].append({'source':label,'exit_code':code});save()
        report['status']='partial_failure' if any(step['exit_code'] for step in report['steps']) else 'completed'
        report['finished_at']=datetime.now(timezone.utc).isoformat();save()
        return int(report['status']!='completed')
    finally:lock.close()

if __name__=='__main__':raise SystemExit(main())
