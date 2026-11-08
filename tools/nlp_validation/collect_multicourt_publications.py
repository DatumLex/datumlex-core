"""Bounded civil-liability acórdão publications across the ten active courts."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
import hashlib
import html
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from collect_djen_acordaos import ROOT, COURTS, ENDPOINT, is_acordao
from src.services.period import today


def civil_text(value):
    text=html.unescape(re.sub(r'<[^>]+>',' ',str(value)))
    return bool(re.search(r'responsabilidade\s+civil|danos?\s+mora(?:l|is)|danos?\s+materia(?:l|is)|dever\s+de\s+indenizar',text,re.I))

def eligible(record,court,start,end):
    try:day=date.fromisoformat(str(record.get('data_disponibilizacao',''))[:10])
    except ValueError:return False
    return (start<=day<=end and is_acordao(record,court,day.isoformat())
            and record.get('segredoJustica') is not True and record.get('sigiloso') is not True
            and civil_text(record.get('texto','')))

def save(path,value):
    from etl_runtime import atomic_json
    atomic_json(path,value)


def fetch_court(court,start,end,page,max_pages):
    pages=[];error=None
    for number in range(page,page+max_pages):
        url=ENDPOINT+'?'+urlencode({'siglaTribunal':court,'dataDisponibilizacaoInicio':start.isoformat(),
            'dataDisponibilizacaoFim':end.isoformat(),'pagina':number,'itensPorPagina':25,'texto':'responsabilidade civil'})
        try:
            for attempt in range(2):
                try:
                    with urlopen(url,timeout=20) as response:raw=response.read(5_000_001)
                    break
                except (HTTPError,URLError,TimeoutError) as exc:
                    if attempt or isinstance(exc,HTTPError) and exc.code not in (408,429,500,502,503,504):raise
                    time.sleep(1)
            if len(raw)>5_000_000:raise ValueError('Response exceeds bounded 5 MB')
            payload=json.loads(raw);rows=payload.get('items')
            if not isinstance(rows,list) or len(rows)>25:raise ValueError('Unexpected DJEN schema or page size')
            pages.append((number,url,raw,rows))
            if len(rows)<25:break
            time.sleep(.3)
        except Exception as exc:
            error={'error_type':type(exc).__name__,'http_status':getattr(exc,'code',None)};break
    return court,pages,error


def collect(limit=1000,days=30):
    from etl_runtime import file_lock
    directory_path=ROOT / 'djen-documents'
    directory_path.mkdir(parents=True,exist_ok=True)
    with file_lock(directory_path/'source.lock'):
        return _collect(limit, days)

def _collect(limit=1000,days=30):
    if not 250<=limit<=1000 or not 1<=days<=90:raise ValueError('Use limit 250..1000 and days 1..90')
    directory=ROOT/'djen-documents';directory.mkdir(parents=True,exist_ok=True)
    pages_dir=directory/'pages';pages_dir.mkdir(exist_ok=True)
    queue_path=directory/'queue.json'
    queue={row['document_id']:row for row in json.loads(queue_path.read_text(encoding='utf8'))} if queue_path.exists() else {}
    end=today()-timedelta(days=1);start=max(date(2016,1,1),end-timedelta(days=days-1))
    scope={'start':start.isoformat(),'end':end.isoformat(),'query':'responsabilidade civil','page_size':25,'courts':list(COURTS)}
    digest=hashlib.sha256(json.dumps(scope,sort_keys=True).encode()).hexdigest()
    cursor_dir=directory/'multicourt-cursors';cursor_dir.mkdir(exist_ok=True)
    cursor_path=cursor_dir/(digest+'.json')
    cursor=json.loads(cursor_path.read_text(encoding='utf8')) if cursor_path.exists() else {'scope':scope,'courts':{}}
    per_court_pages=limit//(25*len(COURTS))
    statuses={};new_total=returned=0
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(fetch_court,court,start,end,cursor['courts'].get(court,{}).get('next_page',1),per_court_pages)
                 for court in COURTS if not cursor['courts'].get(court,{}).get('exhausted')]
        for future in as_completed(futures):
            court,pages,error=future.result();new=selected=scanned=0
            for number,url,raw,rows in pages:
                sha=hashlib.sha256(raw).hexdigest();artifact=pages_dir/f'{court}-{end}-{number}-{sha}.json'
                from etl_runtime import archive_bytes
                archive_bytes(artifact,raw)
                scanned+=len(rows)
                for record in rows:
                    if not record.get('id') or not eligible(record,court,start,end):continue
                    selected+=1;key=f'{court}:DJEN:{record["id"]}'
                    new+=int(key not in queue)
                    source_url=url
                    if re.fullmatch(r'[A-Za-z0-9]{10,100}',str(record.get('hash',''))):source_url=ENDPOINT+'/'+record['hash']+'/certidao'
                    queue[key]={'document_id':key,'court':court,'record_id':str(record['id']),
                        'source_format':'djen-public-json-v1','content_kind':'publication_excerpt','text_field':'texto',
                        'artifact_path':artifact.relative_to(ROOT).as_posix(),'artifact_sha256':sha,
                        'text_sha256':hashlib.sha256(record['texto'].encode()).hexdigest(),'source_version':sha,
                        'publication_date':str(record['data_disponibilizacao'])[:10],
                        'process_number':record.get('numero_processo'),'source_url':source_url,
                        'source_locator':{'endpoint':url,'record_id':str(record['id']),'field':'texto'}}
                save(queue_path,list(queue.values()))
                cursor['courts'][court]={'next_page':number+1,'exhausted':len(rows)<25}
                save(cursor_path,cursor)
            state='partial_source_failure' if error and pages else 'source_unavailable' if error else 'acquired' if selected else 'no_eligible_publication_in_sample'
            statuses[court]={'state':state,'scanned':scanned,'eligible':selected,'new':new,**(error or {})}
            new_total+=new;returned+=scanned
            print(json.dumps({'court':court,**statuses[court]}),flush=True)
    for court in COURTS:
        if court not in statuses:statuses[court]={'state':'previously_exhausted_in_this_window','new':0,'scanned':0,'eligible':0}
    result={'new':new_total,'returned':returned,'content_kind':'publication_excerpt','full_texts':0,
            'scope':scope,'source_status':statuses,
            'source_failures':sum('failure' in item['state'] or item['state']=='source_unavailable' for item in statuses.values()),
            'note':'Publicacoes de acordaos, nao inteiro teor nem cobertura historica 2016..hoje.'}
    save(directory/'multicourt-last-run.json',result)
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--limit',type=int,default=1000);parser.add_argument('--days',type=int,default=30)
    args=parser.parse_args();result=collect(args.limit,args.days)
    print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(2 if result['source_failures'] else 0)
