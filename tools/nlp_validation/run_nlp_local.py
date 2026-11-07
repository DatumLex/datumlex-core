"""Process archived STJ texts offline. Never connects to a DB or approves evidence."""
import argparse
from collections import Counter
from datetime import date, datetime
import json
import shutil
from uuid import UUID
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROOT = PROJECT_ROOT / 'backend/data/operations'
BACKEND = PROJECT_ROOT / 'backend'
sys.path.insert(0, str(BACKEND))
from src.nlp.contracts import bytes_hash  # noqa: E402
from src.services.period import today  # noqa: E402
from src.db.court_catalog import ACTIVE_COURTS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', type=date.fromisoformat, default=date(2016, 1, 1))
    parser.add_argument('--end', type=date.fromisoformat, default=today())
    parser.add_argument("--job-id", type=UUID)
    parser.add_argument('--sources', default='tjdft,ementas,djen,doctrine,pangea')
    args = parser.parse_args()
    selected = set(args.sources.split(','))
    if not selected or selected - {'tjdft', 'ementas', 'djen', 'doctrine', 'pangea'}:
        parser.error('Unknown source')
    if not date(2016, 1, 1) <= args.start <= args.end <= today():
        parser.error('Use 2016-01-01 through today, in chronological order')
    source = ROOT / 'stj-documents'
    base_output = ROOT / 'nlp-local'
    output = base_output / 'jobs' / str(args.job_id) if args.job_id else base_output
    output.mkdir(parents=True, exist_ok=True)
    records = {}
    conflicts = set()
    for metadata in sorted(source.glob('metadata-*.json')):
        rows = json.loads(metadata.read_text(encoding='utf-8-sig'))
        for row in rows:
            key = str(row.get('SeqDocumento', row.get('seqDocumento', '')))
            if key in records and records[key] != row:
                conflicts.add(key)
            records[key] = row
    queue, excluded, years = [], Counter(), Counter()
    for path in sorted((source / 'texts').glob('*.txt')) if 'ementas' in selected else []:
        key = path.name.split('-')[0]
        row = records.get(key)
        if row is None or key in conflicts:
            excluded['missing_or_conflicting_metadata'] += 1
            continue
        try:
            value = row['dataPublicacao']
            published = (datetime.fromtimestamp(value / 1000, ZoneInfo('America/Sao_Paulo')).date()
                         if isinstance(value, (int, float)) and not isinstance(value, bool)
                         else date.fromisoformat(str(value)[:10]))
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            excluded['invalid_publication_date'] += 1
            continue
        if not args.start <= published <= args.end:
            excluded['outside_publication_period'] += 1
            continue
        raw = path.read_bytes()
        text = raw.decode('utf-8', errors='strict')
        queue.append({'document_id': 'STJ:' + key, 'court': 'STJ',
                      'artifact_path': str(path.relative_to(ROOT)), 'artifact_sha256': bytes_hash(raw),
                      'text_sha256': bytes_hash(text.encode('utf-8')),
                      'source_version': bytes_hash(raw), 'publication_date': published.isoformat()})
        years[str(published.year)] += 1
    # Merge verified full-text TJDFT records; do not infer a text from an ementa.
    tjdft_index = ROOT / 'tjdft-documents/documents.json'
    if 'tjdft' in selected and tjdft_index.exists():
        from src.nlp.adapters import read_source
        for row in json.loads(tjdft_index.read_text(encoding='utf8')).values():
            decision = date.fromisoformat(row['decision_date'])
            if args.start <= decision <= args.end:
                read_source(row, ROOT)
                queue.append(row)
                years[str(decision.year)] += 1
    queue_path = output / 'queue.json'
    extra = ROOT / 'jurisprudence-ementas/queue.json'
    if 'ementas' in selected and extra.exists():
        from src.nlp.adapters import read_source
        for row in json.loads(extra.read_text(encoding='utf8')):
            decision = date.fromisoformat(row['decision_date'])
            if args.start <= decision <= args.end:
                read_source(row, ROOT)
                queue.append(row)
                years[str(decision.year)] += 1
    publications = ROOT / 'djen-documents/queue.json'
    if 'djen' in selected and publications.exists():
        from src.nlp.adapters import read_source
        for row in json.loads(publications.read_text(encoding='utf8')):
            if row['court'] not in ACTIVE_COURTS:
                excluded['inactive_court_archived'] += 1
                continue
            published = date.fromisoformat(row['publication_date'])
            if args.start <= published <= args.end:
                read_source(row, ROOT)
                queue.append(row)
                years[str(published.year)] += 1
    from src.nlp.reference_sources import reference_queue
    reference_rows, reference_exclusions = reference_queue(ROOT, selected)
    excluded.update(reference_exclusions)
    for row in reference_rows:
        publication = row.get('publication_date')
        if publication and not args.start <= date.fromisoformat(publication[:10]) <= args.end:
            excluded['outside_reference_publication_period'] += 1
            continue
        queue.append(row)
        if publication:
            years[publication[:4]] += 1
    queue = [row for row in queue if row.get('court') in ACTIVE_COURTS
             or row.get('category') == 'doctrine' and row.get('court') == '']
    queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding='utf-8')
    coverage = {'requested_start': args.start.isoformat(), 'requested_end': args.end.isoformat(),
                'period_field': 'Per record: decision_date when supplied; otherwise publication_date', 'local_texts_selected': len(queue),
                'period_fields_by_content': {'STJ_full_text': 'publication_date', 'TJDFT_full_text': 'decision_date',
                    'STJ_ementa': 'decision_date', 'TST_ementa': 'decision_date', 'DJEN_publication_excerpt': 'publication_date'},
                'texts_by_court': dict(Counter(row['court'] for row in queue if row['court'])),
                'texts_by_publisher': dict(Counter(row['source_name'] for row in queue if row.get('category') == 'doctrine')),
                'content_kinds': dict(Counter(row.get('content_kind', 'full_text') for row in queue)),
                'texts_by_court_year': dict(Counter(row['court'] + ':' + (row.get('decision_date') or row.get('publication_date'))[:4]
                                                  for row in queue if row['court'] and (row.get('decision_date') or row.get('publication_date')))),
                'undated_references': sum(not row.get('decision_date') and not row.get('publication_date') for row in queue
                                         if row.get('category') in ('precedent', 'doctrine')),
                'categories': dict(Counter(row.get('category', 'jurisprudence') for row in queue)),
                'texts_by_year': dict(years), 'exclusions': dict(excluded),
                'years_without_local_texts': [year for year in range(args.start.year, args.end.year + 1)
                                             if not years.get(str(year))],
                'review_status': 'pending', 'release_status': 'not_released',
                'note': 'Local archived texts only. No historical completeness or legal approval asserted.'}
    (output / 'coverage.json').write_text(json.dumps(coverage, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(coverage, ensure_ascii=False, indent=2), flush=True)
    if not queue:
        if selected <= {'doctrine', 'pangea'}:
            (output / 'current-run.json').write_text(json.dumps({
                'status': 'no_eligible_text', 'directory': None,
            }), encoding='utf8')
            return 0
        return 1
    result = subprocess.run([sys.executable, '-m', 'src.nlp', '--root', str(ROOT),
                            '--queue', str(queue_path), '--output', str(output / 'runs'),
                            '--guide', str(BACKEND / 'src/nlp/prompt.txt'),
                            '--computation-cache', str(base_output / 'computation-cache'),
                            '--allow-unreviewed-calibration'], cwd=BACKEND,
                            stdout=subprocess.PIPE, text=True, encoding='utf8')
    print(result.stdout, end='')
    if result.stderr:
        print(result.stderr, end='', file=sys.stderr)
    if result.returncode == 0:
        run = json.loads(result.stdout)
        (output / 'current-run.json').write_text(json.dumps({'directory': run['output']}), encoding='utf8')
        if args.job_id:
            for name in ('queue.json','coverage.json','current-run.json'):
                temporary = base_output / (name + '.part')
                shutil.copyfile(output / name, temporary)
                temporary.replace(base_output / name)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
