"""Report observed collection gaps and select the next focused Pangea query."""
import json
from pathlib import Path
import sys

from etl_runtime import atomic_json

BACKEND = Path(__file__).resolve().parents[2] / 'backend'
sys.path.insert(0, str(BACKEND))
from src.db.court_catalog import ACTIVE_COURTS
from src.services.period import today

BROAD_QUERY = 'responsabilidade civil'
FOCUSED_QUERIES = ('dano moral', 'negativação indevida')


def read_json(path):
    return json.loads(path.read_bytes()) if path.exists() else {}


def pangea_reports(root):
    path = root / 'pangea-raw'
    reports = {}
    for manifest in [path / 'manifest.json', *sorted(path.glob('scopes/*/manifest.json'))]:
        report = read_json(manifest)
        if set(report.get('courts', ())) != set(ACTIVE_COURTS) or report.get('page_size') != 100:
            continue
        query = report['query']
        if report['started_at'] >= reports.get(query, {}).get('started_at', ''):
            reports[query] = report
    return reports


def next_focused_query(root):
    reports = pangea_reports(root)
    return min(FOCUSED_QUERIES, key=lambda query: reports.get(query, {}).get('started_at', ''))


def report_coverage(root):
    tjdft = root / 'tjdft-documents'
    cursor = read_json(tjdft / 'cursor.json').get('years', {})
    documents = read_json(tjdft / 'documents.json').values()
    by_year = {}
    for row in documents:
        year = (row.get('decision_date') or '')[:4]
        counts = by_year.setdefault(year, {'indexed': 0, 'missing_process_number': 0,
                                          'missing_publication_date': 0})
        counts['indexed'] += 1
        counts['missing_process_number'] += not row.get('process_number')
        counts['missing_publication_date'] += not row.get('publication_date')
    tjdft_scopes = {}
    for year in range(2016, today().year + 1):
        key = str(year)
        progress = cursor.get(key, {})
        counts = by_year.get(key, {'indexed': 0, 'missing_process_number': 0,
                                   'missing_publication_date': 0})
        fallback = 'legacy_unknown' if progress or counts['indexed'] else 'not_checked'
        tjdft_scopes[key] = {**counts, 'next_page': progress.get('page', 0),
                            'exhausted': progress.get('exhausted', False),
                            'last_probe': progress.get('last_probe', {'status': fallback})}

    reports = pangea_reports(root)
    pangea_scopes = {}
    for query in (BROAD_QUERY, *FOCUSED_QUERIES):
        report = reports.get(query, {})
        status = report.get('status', 'not_checked')
        if status == 'completed' and report.get('rows_returned') == 0:
            status = 'empty_page'
        pangea_scopes[query] = {
            'status': status, 'started_at': report.get('started_at'),
            'source_total': report.get('source_total'), 'rows_by_court': report.get('rows_by_court'),
            'failed_stage': report.get('failed_stage'), 'failed_page': report.get('failed_page'),
        }
    return {
        'tjdft': {'court': 'TJDFT', 'query': BROAD_QUERY, 'years': tjdft_scopes},
        'pangea': {'courts': list(ACTIVE_COURTS), 'period': None, 'queries': pangea_scopes},
    }


if __name__ == '__main__':
    root = BACKEND / 'data/operations'
    atomic_json(root / 'collection-coverage.json', report_coverage(root))
