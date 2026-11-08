"""Bounded annual round-robin collection of public TJDFT full-text decisions.

Official API documentation and public JurisDF request contract:
https://www.tjdft.jus.br/transparencia/tecnologia-da-informacao-e-comunicacao/dados-abertos/
"""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT = Path(__file__).resolve().parents[2]
ROOT = PROJECT / 'backend/data/operations'
sys.path.insert(0, str(PROJECT / 'backend'))
from src.services.period import today

ENDPOINT = 'https://jurisdf.tjdft.jus.br/api/v1/pesquisa'


def fetch_page(request, attempts=3):
    """Retry only transient failures; never advance a cursor on a failed page."""
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=45) as response:
                if response.url != ENDPOINT:
                    raise ValueError('Unexpected source redirect')
                raw = response.read(20_000_001)
            if len(raw) > 20_000_000:
                raise ValueError('Response exceeds 20 MB limit')
            return raw
        except (HTTPError, URLError, TimeoutError) as exc:
            if isinstance(exc, HTTPError) and exc.code not in (408, 429, 500, 502, 503, 504):
                raise
            if attempt + 1 == attempts:
                raise
            time.sleep(2 ** attempt)


def save(path,value):
    from etl_runtime import atomic_json
    atomic_json(path,value)


def eligible(row, year):
    if row.get('segredoJustica') is not False:
        return False
    value = row.get('dataJulgamento')
    try:
        day = date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return False
    return (day.year == year and day <= today() and isinstance(row.get('uuid'), str)
            and bool(row['uuid']) and isinstance(row.get('inteiroTeor'), str)
            and bool(row['inteiroTeor'].strip()))



def collect(limit=275, page_size=25, directory=None, target_total=None):
    from etl_runtime import file_lock
    directory_path=directory or ROOT / 'tjdft-documents'
    directory_path.mkdir(parents=True,exist_ok=True)
    with file_lock(directory_path/'source.lock'):
        return _collect(limit, page_size, directory, target_total)

def _collect(limit=275, page_size=25, directory=None, target_total=None):
    if not 1 <= limit <= 1000 or not 1 <= page_size <= 25:
        raise ValueError('Use limit 1..1000 and page size 1..25')
    directory = directory or ROOT / 'tjdft-documents'
    pages = directory / 'pages'
    pages.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(directory).free < 1_000_000_000:
        raise ValueError('Less than 1 GB free; collection stopped')
    state_path, index_path = directory / 'cursor.json', directory / 'documents.json'
    state = json.loads(state_path.read_text(encoding='utf8')) if state_path.exists() else {'next_year': 2016, 'years': {}}
    index = json.loads(index_path.read_text(encoding='utf8')) if index_path.exists() else {}
    # The page size is part of the cursor identity: changing it would skip records.
    if state.get('page_size', page_size) != page_size:
        raise ValueError('Existing cursor uses another page size')
    state['page_size'] = page_size
    fetched = added = excluded = 0
    downloaded = 0
    years = list(range(2016, today().year + 1))
    visited_empty = set()
    while (fetched + page_size <= limit and len(visited_empty) < len(years)
           and (target_total is None or len(index) < target_total)):
        year = state['next_year']
        state['next_year'] = years[(years.index(year) + 1) % len(years)]
        progress = state['years'].setdefault(str(year), {'page': 0, 'exhausted': False})
        if progress['exhausted']:
            visited_empty.add(year)
            continue
        end = min(date(year, 12, 31), today())
        body = {'query': 'responsabilidade civil', 'pagina': progress['page'], 'tamanho': page_size,
                'retornaInteiroTeor': True, 'retornaTotalizacao': False,
                'sinonimos': False, 'espelho': True,
                'termosAcessorios': [{'campo': 'base', 'valor': 'acordaos'},
                    {'campo': 'segredoJustica', 'valor': 'false'},
                    {'campo': 'dataJulgamento', 'valor': f'entre {year}-01-01 e {end.isoformat()}'}]}
        request = Request(ENDPOINT, data=json.dumps(body).encode(),
                          headers={'Content-Type': 'application/json', 'User-Agent': 'DatumLex-local-research/1.0'})
        try:
            raw = fetch_page(request)
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            # Keep this page pending and replace any stale successful run report.
            state['next_year'] = year
            save(state_path, state)
            save(directory / 'last-run.json', {
                'status': 'failed', 'fetched': fetched, 'new': added,
                'excluded': excluded, 'full_texts_indexed': len(index),
                'failed_year': year, 'failed_page': progress['page'],
                'error_type': type(exc).__name__, 'review_status': 'pending'})
            raise
        downloaded += len(raw)
        if downloaded > 200_000_000:
            raise ValueError('Run exceeds 200 MB limit')
        payload = json.loads(raw)
        records = payload.get('registros')
        if not isinstance(records, list) or len(records) > page_size:
            raise ValueError('Unexpected TJDFT response schema')
        digest = hashlib.sha256(raw).hexdigest()
        artifact = pages / f'{year}-{progress["page"]:06}-{digest}.json'
        from etl_runtime import archive_bytes
        archive_bytes(artifact,raw)
        # Persist each page before advancing its cursor. A retry is idempotent by UUID.
        truncated_by_target = False
        for row in records:
            if not eligible(row, year):
                excluded += 1
                continue
            key = row['uuid']
            if target_total is not None and len(index) >= target_total and key not in index:
                truncated_by_target = True
                continue
            added += int(key not in index)
            index[key] = {'document_id': 'TJDFT:' + key, 'court': 'TJDFT',
                'artifact_path': artifact.relative_to(ROOT).as_posix(), 'artifact_sha256': digest,
                'text_sha256': hashlib.sha256(row['inteiroTeor'].encode()).hexdigest(),
                'text_field': 'inteiroTeor', 'source_version': str(row.get('versao', digest)),
                'decision_date': row['dataJulgamento'][:10],
                'publication_date': str(row.get('dataPublicacao') or '')[:10] or None,
                'process_number': row.get('processo'),
                'source_url': 'https://jurisdf.tjdft.jus.br/acordaos/' + key,
                'source_locator': {'endpoint': ENDPOINT, 'query': body, 'uuid': key}}
        fetched += len(records)
        if truncated_by_target:
            state['next_year'] = year
        else:
            progress['page'] += 1
        progress['exhausted'] = not truncated_by_target and len(records) < page_size
        if progress['exhausted']:
            visited_empty.add(year)
        save(index_path, index)
        save(state_path, state)
        print(json.dumps({'year': year, 'page': progress['page'] - (0 if truncated_by_target else 1), 'fetched': len(records),
                          'new_this_run': added, 'full_texts_indexed': len(index)}, ensure_ascii=False), flush=True)
        time.sleep(.3)
    summary = {'status': 'completed', 'fetched': fetched, 'new': added, 'excluded': excluded, 'full_texts_indexed': len(index),
               'coverage': 'partial_public_search_results_not_a_census', 'query': 'responsabilidade civil',
               'review_status': 'pending'}
    save(directory / 'last-run.json', summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=275)
    parser.add_argument('--target',type=int)
    args = parser.parse_args()
    print(json.dumps(collect(args.limit, target_total=args.target), ensure_ascii=False, indent=2))
