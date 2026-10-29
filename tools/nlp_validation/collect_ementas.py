"""Collect official STJ/TST ementas, explicitly separate from complete decisions."""
import argparse
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.request import Request, urlopen

PROJECT = Path(__file__).resolve().parents[2]
ROOT = PROJECT / 'backend/data/operations'
sys.path.insert(0, str(PROJECT / 'backend'))
from src.services.period import today


def request(url, body=None):
    req = Request(url, data=json.dumps(body).encode() if body is not None else None,
                  headers={'Content-Type': 'application/json', 'User-Agent': 'DatumLex-local-research/1.0'})
    with urlopen(req, timeout=40) as response:
        raw = response.read(20_000_001)
    if len(raw) > 20_000_000:
        raise ValueError('Response exceeds bounded 20 MB')
    return raw, json.loads(raw)


def decision_date(value):
    text = str(value or '')
    if re.fullmatch(r'\d{8}', text):
        return datetime.strptime(text, '%Y%m%d').date()
    return date.fromisoformat(text[:10])



def collect(limit=300):
    from etl_runtime import file_lock
    directory_path=ROOT / 'jurisprudence-ementas'
    directory_path.mkdir(parents=True,exist_ok=True)
    with file_lock(directory_path/'source.lock'):
        return _collect(limit)

def _collect(limit=300):
    if not 1 <= limit <= 1000:
        raise ValueError('Limit must be 1..1000')
    directory = ROOT / 'jurisprudence-ementas'
    pages = directory / 'pages'
    pages.mkdir(parents=True, exist_ok=True)
    queue_path = directory / 'queue.json'
    queue = {row['document_id']: row for row in json.loads(queue_path.read_text(encoding='utf8'))} if queue_path.exists() else {}
    new = 0
    cursor_path = directory / 'cursor.json'
    cursor = json.loads(cursor_path.read_text(encoding='utf8')) if cursor_path.exists() else {'stj_resource_offset': 0, 'tst_page': 0}
    failures = []

    def save_cursor():
        from etl_runtime import atomic_json
        atomic_json(cursor_path,cursor)

    def archive(court, url, raw, records, fmt, ceiling=None):
        nonlocal new
        sha = hashlib.sha256(raw).hexdigest()
        path = pages / f'{court}-{sha}.json'
        from etl_runtime import archive_bytes
        archive_bytes(path,raw)
        exhausted = True
        for record in records:
            if new >= (ceiling if ceiling is not None else limit):
                exhausted = False
                break
            text = record.get('ementa')
            if not isinstance(text, str) or len(text.strip()) < 100 or text == 'removido no backend':
                continue
            try:
                day = decision_date(record.get('dataDecisao') if court == 'STJ' else record.get('dtaJulgamento'))
            except (ValueError, TypeError):
                continue
            if not date(2016, 1, 1) <= day <= today():
                continue
            identity = str(record.get('id', ''))
            if not identity:
                continue
            key = f'{court}:EMENTA:{identity}'
            new += int(key not in queue)
            queue[key] = {'document_id': key, 'court': court, 'record_id': identity,
                'source_format': fmt, 'content_kind': 'ementa', 'text_field': 'ementa',
                'artifact_path': path.relative_to(ROOT).as_posix(), 'artifact_sha256': sha,
                'text_sha256': hashlib.sha256(text.encode()).hexdigest(), 'source_version': sha,
                'decision_date': day.isoformat(), 'source_url': url,
                'source_locator': {'record_id': identity, 'field': 'ementa', 'endpoint': url}}
        from etl_runtime import atomic_json
        atomic_json(queue_path,list(queue.values()))
        return exhausted

    # Rotate across all monthly civil-panel resources instead of one month per year.
    catalog_url = 'https://dadosabertos.web.stj.jus.br/api/3/action/package_search?q=groups:jurisprudencia&rows=20'
    per_stj_limit = limit // 2
    try:
        _, catalog = request(catalog_url)
        resources = sorted({r['url'] for package in catalog['result']['results']
            if package['name'] in ('espelhos-de-acordaos-terceira-turma','espelhos-de-acordaos-quarta-turma')
            for r in package['resources'] if re.search(r'/\d{8}\.json$',r.get('url',''))})
        for _ in range(min(4,len(resources))):
            if new>=per_stj_limit:break
            offset=cursor['stj_resource_offset'] % len(resources)
            url=resources[offset]
            try:
                raw,rows=request(url)
                if not isinstance(rows,list):raise ValueError('Unexpected STJ archive')
                rows=[r for r in rows if re.search(r'responsabilidade civil|danos? mora(?:l|is)|danos? materia(?:l|is)',r.get('ementa') or '',re.I)]
                complete=archive('STJ',url,raw,rows,'stj-espelhos-json-v1',per_stj_limit)
                cursor['stj_resource_offset']=(offset+1)%len(resources) if complete else offset
                save_cursor()
                print(json.dumps({'court':'STJ','resource':url,'new':new}),flush=True)
                if not complete:break
            except Exception as exc:
                failures.append({'court':'STJ','resource':url,'error_type':type(exc).__name__})
                cursor['stj_resource_offset']=(offset+1)%len(resources);save_cursor()
            time.sleep(.3)
    except Exception as exc:
        failures.append({'court':'STJ','error_type':type(exc).__name__})
    try:
        _, config = request('https://jurisprudencia.tst.jus.br/config.json')
        backend = config['base_url'].rstrip('/')
        if backend not in ('https://jurisprudencia-backend.tst.jus.br', 'https://jurisprudencia-backend2.tst.jus.br'):
            raise ValueError('Unexpected TST backend')
        page = cursor['tst_page']
        pages_this_run = 0
        while new < limit and pages_this_run < 20:
            body = {'ou': '', 'e': 'dano moral', 'termoExato': '', 'naoContem': '', 'ementa': '',
                    'dispositivo': '', 'numeracaoUnica': {'numero': '', 'ano': '', 'digito': '', 'orgao': '5', 'tribunal': '', 'vara': ''},
                    'orgaosJudicantes': [], 'ministros': [], 'convocados': [], 'classesProcessuais': [],
                    'codigosClassesPrecedentes': [], 'indicadores': [], 'assuntos': [],
                    'tipos': ['ACORDAO'], 'tiposPaginacao': ['ACORDAO'], 'orgao': 'TST', 'ordenacao': 'data'}
            url = backend + f'/rest/pesquisa-textual/{page * 25 + 1}/25'
            raw, payload = request(url, body)
            records = [item['registro'] for item in payload['registros']]
            records = [r for r in records if r.get('orgao', {}).get('sigla') == 'TST'
                       and r.get('tipo', {}).get('codigoTipoJurisprudencia') == 'ACORDAO']
            complete = archive('TST', url, raw, records, 'tst-search-json-v1')
            cursor['tst_page'] = page + 1 if complete and records else page
            save_cursor()
            print(json.dumps({'court': 'TST', 'page': page, 'new': new}), flush=True)
            if len(records) < 25 or not complete:
                break
            page += 1
            pages_this_run += 1
            time.sleep(.3)
    except Exception as exc:
        failures.append({'court':'TST','error_type':type(exc).__name__})
    result = {'new': new, 'ementas_archived': len(queue), 'content_kind': 'ementa',
              'full_texts': 0, 'source_failures': failures, 'legal_review': 'pending'}
    (directory / 'last-run.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=300)
    args = parser.parse_args()
    result = collect(args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(2 if result['source_failures'] else 0)
