"""Public DJEN acórdão publications by court. These are not full judgments.

Only GET is used. Publication type, source court and date are verified locally:
unknown API filters are never trusted as proof that a result is an acórdão.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import urlencode
from urllib.request import urlopen

PROJECT = Path(__file__).resolve().parents[2]
ROOT = PROJECT / 'backend/data/operations'
sys.path.insert(0, str(PROJECT / 'backend'))
from src.db.court_catalog import ACTIVE_COURTS as COURTS, matches_source
from src.services.period import today

ENDPOINT = 'https://comunicaapi.pje.jus.br/api/v1/comunicacao'


def is_acordao(record, court, day):
    kind = ''.join(c for c in unicodedata.normalize('NFD', str(record.get('tipoDocumento', '')))
                   if unicodedata.category(c) != 'Mn').casefold()
    return ('acordao' in kind and matches_source(court, record.get('siglaTribunal'))
            and record.get('ativo') is not False and not record.get('data_cancelamento')
            and str(record.get('data_disponibilizacao', ''))[:10] == day
            and isinstance(record.get('texto'), str) and len(record['texto'].strip()) >= 200)


def fetch(court, day):
    parameters = {'siglaTribunal': court, 'dataDisponibilizacaoInicio': day,
                  'dataDisponibilizacaoFim': day, 'pagina': 1, 'itensPorPagina': 5,
                  'texto': 'acórdão'}
    url = ENDPOINT + '?' + urlencode(parameters)
    try:
        with urlopen(url, timeout=15) as response:
            raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError('response_too_large')
        payload = json.loads(raw)
        if not isinstance(payload.get('items'), list) or len(payload['items']) > 5:
            raise ValueError('page_limit_or_schema_mismatch')
        return court, url, raw, payload, None
    except Exception as exc:
        return court, url, None, None, {'type': type(exc).__name__, 'http_status': getattr(exc, 'code', None)}



def collect(limit=455):
    from etl_runtime import file_lock
    directory_path=ROOT / 'djen-documents'
    directory_path.mkdir(parents=True,exist_ok=True)
    with file_lock(directory_path/'source.lock'):
        return _collect(limit)

def _collect(limit=455):
    if not 5 <= limit <= 1000:
        raise ValueError('Limit must be 5..1000')
    directory = ROOT / 'djen-documents'
    pages = directory / 'pages'
    pages.mkdir(parents=True, exist_ok=True)
    queue_path = directory / 'queue.json'
    queue = {r['document_id']: r for r in json.loads(queue_path.read_text(encoding='utf8'))} if queue_path.exists() else {}
    cursor_path = directory / 'court-cursor.json'
    offset = json.loads(cursor_path.read_text())['offset'] if cursor_path.exists() else 0
    count = min(len(COURTS), limit // 5)
    courts = [COURTS[(offset + i) % len(COURTS)] for i in range(count)]
    day = (today() - timedelta(days=1)).isoformat()
    status, new, fetched = {}, 0, 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(fetch, court, day) for court in courts]
        for future in as_completed(futures):
            court, url, raw, payload, error = future.result()
            if error:
                status[court] = {'state': 'source_unavailable', **error}
                continue
            digest = hashlib.sha256(raw).hexdigest()
            artifact = pages / f'{court}-{day}-{digest}.json'
            from etl_runtime import archive_bytes
            archive_bytes(artifact,raw)
            records = payload['items']
            fetched += len(records)
            selected = [r for r in records if is_acordao(r, court, day)]
            for record in selected:
                identity = str(record['id'])
                key = f'{court}:DJEN:{identity}'
                new += int(key not in queue)
                source_url = url
                if re.fullmatch(r'[A-Za-z0-9]{10,100}', str(record.get('hash', ''))):
                    source_url = ENDPOINT + '/' + record['hash'] + '/certidao'
                queue[key] = {'document_id': key, 'court': court, 'record_id': identity,
                    'source_format': 'djen-public-json-v1', 'content_kind': 'publication_excerpt',
                    'text_field': 'texto', 'artifact_path': artifact.relative_to(ROOT).as_posix(),
                    'artifact_sha256': digest, 'text_sha256': hashlib.sha256(record['texto'].encode()).hexdigest(),
                    'source_version': digest, 'publication_date': day,
                    'process_number': record.get('numero_processo'), 'source_url': source_url,
                    'source_locator': {'endpoint': url, 'record_id': identity, 'field': 'texto'}}
            status[court] = {'state': 'publications_acquired' if selected else 'no_eligible_acordao_in_sample',
                             'returned': len(records), 'acordao_publications': len(selected), 'date': day}
            print(json.dumps({'court': court, **status[court]}, ensure_ascii=False), flush=True)
    from etl_runtime import atomic_json
    atomic_json(queue_path,list(queue.values()))
    atomic_json(cursor_path,{'offset': (offset + count) % len(COURTS)})
    report = {'new': new, 'returned': fetched, 'content_kind': 'publication_excerpt', 'full_texts': 0,
              'source_failures': sum(s['state'] == 'source_unavailable' for s in status.values()),
              'queried_courts': len(courts), 'source_status': status, 'date': day,
              'note': 'First-page sample only; not absence of jurisprudence or historical coverage.'}
    (directory / 'last-run.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=455)
    args = parser.parse_args()
    result = collect(args.limit)
    print(json.dumps({k: v for k, v in result.items() if k != 'source_status'}, ensure_ascii=False, indent=2))
    raise SystemExit(2 if result['source_failures'] else 0)
