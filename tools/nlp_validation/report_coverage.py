"""Coverage ledger: acquired content by court/type/year, including missing coverage."""
from collections import Counter
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[2]
ROOT = PROJECT / 'backend/data/operations'
sys.path.insert(0, str(PROJECT / 'backend'))
from src.db.court_catalog import ACTIVE_COURTS as COURTS
from src.services.period import today


def main():
    queue = json.loads((ROOT / 'nlp-local/queue.json').read_text(encoding='utf8'))
    latest = ROOT / 'djen-documents/last-run.json'
    probes = json.loads(latest.read_text(encoding='utf8')).get('source_status', {}) if latest.exists() else {}
    unique = {row['document_id']: row for row in queue if row['court'] in COURTS}
    total = Counter(row.get('content_kind', 'full_text') for row in unique.values())
    courts = {}
    for court in COURTS:
        rows = [row for row in unique.values() if row['court'] == court]
        counts = Counter(row.get('content_kind', 'full_text') for row in rows)
        years = Counter((row.get('decision_date') or row['publication_date'])[:4] for row in rows
                        if row.get('content_kind', 'full_text') == 'full_text')
        courts[court] = {'acquired': dict(counts), 'full_text_years': dict(sorted(years.items())),
            'missing_full_text_years': [y for y in range(2016, today().year + 1) if not years[str(y)]],
            'full_text_date_field': 'publication_date' if court == 'STJ' else 'decision_date',
            'latest_publication_probe': probes.get(court),
            'status': 'acquired_partial' if rows else probes.get(court, {}).get('state', 'not_checked')}
    report = {'date': today().isoformat(), 'unique_documents': len(unique), 'content_types': dict(total),
        'registered_courts': len(COURTS), 'courts_with_acquired_content': sum(bool(c['acquired']) for c in courts.values()),
        'courts_with_full_text': sum(bool(c['acquired'].get('full_text')) for c in courts.values()),
        'courts': courts, 'legal_review': 'pending',
        'limitations': ['Registry is not acquired coverage.', 'Ementa and publication excerpt are not full judgment.',
                       'First-page DJEN sample is not a census or proof of absent jurisprudence.',
                       'STJ full-text years use publication date, not a confirmed judgment date.']}
    target = ROOT / 'coverage-by-court.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: v for k, v in report.items() if k != 'courts'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
