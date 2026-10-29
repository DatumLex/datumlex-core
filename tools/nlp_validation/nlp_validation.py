"""Offline, frozen NLP benchmark preparation and strict human-reference scoring."""
import argparse
from collections import Counter
from datetime import date as calendar_date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE = PROJECT_ROOT / 'backend/data/operations'
sys.path.insert(0, str(PROJECT_ROOT / 'backend'))
from src.nlp.adapters import read_source
from src.nlp.contracts import fingerprint
from src.nlp.extraction import extract, RULES_VERSION

LABELS = ('CITED_AUTHORITY', 'LEGAL_THESIS', 'LEGAL_GROUND')
ADOPTIONS = ('adopted', 'rejected', 'mentioned', 'uncertain', 'not_applicable')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def document_key(value):
    return hashlib.sha256(value.encode()).hexdigest()


def prepare(root=BASE, queue_path=None, target=100):
    queue_path = queue_path or root / 'nlp-local/queue.json'
    if not queue_path.exists():
        raise ValueError('Fila local ausente. Prepare os textos e execute run_nlp_local.py antes de montar a amostra.')
    processes = {}
    for path in (root / 'stj-documents').glob('metadata-*.json'):
        for row in read(path):
            key = str(row.get('SeqDocumento', row.get('seqDocumento', '')))
            if row.get('processo'):
                processes['STJ:' + key] = str(row['processo']).strip().casefold()
    candidates, seen = [], set()
    for row in read(queue_path):
        # This benchmark evaluates complete decisions. Ementas need a separate reference.
        if row.get('content_kind', 'full_text') != 'full_text':
            continue
        text = read_source(row, root)
        if row['text_sha256'] in seen:
            continue
        seen.add(row['text_sha256'])
        date = row.get('decision_date') or row.get('publication_date')
        if date:
            calendar_date.fromisoformat(date)
        if not date or not '2016-01-01' <= date <= '2026-12-31':
            continue
        candidates.append({'id': row['document_id'], 'court': row['court'], 'date': date,
                           'period_field': 'decision_date' if row.get('decision_date') else 'publication_date',
                           'text_sha256': row['text_sha256'], 'text': text,
                           'group': row.get('process_number') or processes.get(row['document_id']) or row['text_sha256'],
                           'source': row, 'length': len(text)})
    # Round-robin strata: year, court and length. Do not select using NLP output.
    strata = {}
    for row in candidates:
        key = (row['date'][:4], row['court'], 'short' if row['length'] < 5000 else 'long')
        strata.setdefault(key, []).append(row)
    for rows in strata.values():
        rows.sort(key=lambda row: document_key(row['id']))
    selected = []
    while len(selected) < target and any(strata.values()):
        for key in sorted(strata):
            if strata[key] and len(selected) < target:
                selected.append(strata[key].pop(0))
    # Keep all pilot texts in development until at least 20 groups exist.
    # Shared process/text identity cannot appear on both sides of the split.
    groups = sorted({d['group'] for d in selected}, key=document_key)
    test_groups = set(groups[:max(1, len(groups) * 3 // 10)]) if len(groups) >= 20 else set()
    for row in selected:
        row['split'] = 'test' if row['group'] in test_groups else 'development'
    # Raw full text is exposed to reviewers; model annotations are kept elsewhere.
    predictions = {'rules_version': RULES_VERSION,
                   'code_sha256': hashlib.sha256(Path(sys.modules[extract.__module__].__file__).read_bytes()).hexdigest(),
                   'documents': {}}
    for row in selected:
        annotations, skipped = extract(row['text'])
        predictions['documents'][row['id']] = {'annotations': annotations, 'skipped_intervals': skipped}
    manifest = {'schema': 'local-nlp-benchmark/1', 'target_documents': target,
                'documents': selected, 'labels': LABELS, 'sampling': 'year-court-length-round-robin-v1',
                'predictions_sha256': fingerprint(predictions),
                'split_policy': 'process-grouped-70-30-v1; fewer-than-20-groups-development-only',
                'eligibility': 'local-source-hash-verified; legal-and-source-review-still-required'}
    dataset_id = fingerprint(manifest)
    directory = root / 'nlp-validation' / dataset_id
    if not (directory / 'manifest.json').exists():
        save(directory / 'manifest.json', manifest)
        save(directory / 'predictions.json', {'dataset_id': dataset_id, **predictions})
        save(directory / 'criteria.json', {'approval_reference': None, 'source_approval_reference': None,
              'minimum_documents': target,
              'minimum_test_documents': 20, 'required_courts': ['STJ', 'TJDFT'],
              'required_years': list(range(2016, 2027)), 'minimum_gold_per_label_test': 10,
              'precision': 0.90, 'recall': 0.80,
              'note': 'Proposed pilot thresholds, not a legal or industry standard. Human approval required before use.'})
    save(root / 'nlp-validation/current.json', {'dataset_id': dataset_id, 'directory': str(directory)})
    return directory


def load_dataset(directory):
    directory = Path(directory)
    manifest = read(directory / 'manifest.json')
    if fingerprint(manifest) != directory.name:
        raise ValueError('dataset_integrity_error')
    predictions = read(directory / 'predictions.json')
    if predictions['dataset_id'] != directory.name:
        raise ValueError('prediction_dataset_mismatch')
    if fingerprint({k: v for k, v in predictions.items() if k != 'dataset_id'}) != manifest['predictions_sha256']:
        raise ValueError('prediction_integrity_error')
    return manifest, predictions


def validate_review(payload, document):
    if payload.get('document_id') != document['id'] or payload.get('text_sha256') != document['text_sha256']:
        raise ValueError('review_document_mismatch')
    reviewer = payload.get('reviewer', '')
    if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 100:
        raise ValueError('reviewer_required')
    if type(payload.get('completed')) is not bool:
        raise ValueError('explicit_completion_required')
    annotations = payload.get('annotations')
    if not isinstance(annotations, list):
        raise ValueError('annotations_array_required')
    seen = set()
    for item in annotations:
        if not isinstance(item, dict):
            raise ValueError('annotation_object_required')
        if item.get('label') not in LABELS or item.get('adoption') not in ADOPTIONS:
            raise ValueError('invalid_label_or_adoption')
        start, end = item.get('start'), item.get('end')
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(document['text']):
            raise ValueError('invalid_unicode_offsets')
        if document['text'][start:end] != item.get('text'):
            raise ValueError('quote_mismatch')
        key = (item['label'], start, end)
        if key in seen:
            raise ValueError('duplicate_annotation')
        seen.add(key)
    return payload


def review_path(directory, document_id, reviewer, adjudication=False):
    kind = 'adjudications' if adjudication else 'reviews'
    return Path(directory) / kind / document_key(document_id) / (document_key(reviewer) + '.json')


def reviews_for(directory, document, adjudication=False):
    kind = 'adjudications' if adjudication else 'reviews'
    rows = []
    for path in (Path(directory) / kind / document_key(document['id'])).glob('*.json'):
        row = validate_review(read(path), document)
        if row['completed']:
            rows.append(row)
    return rows


def store_review(directory, payload, adjudication=False):
    manifest, _ = load_dataset(directory)
    document = next((d for d in manifest['documents'] if d['id'] == payload.get('document_id')), None)
    if document is None:
        raise ValueError('unknown_document')
    payload = validate_review(payload, document)
    payload['reviewer'] = payload['reviewer'].strip().casefold()
    if adjudication:
        source = reviews_for(directory, document)
        identities = {r['reviewer'].strip().casefold() for r in source}
        if len(identities) < 2 or payload['reviewer'] in identities:
            raise ValueError('two_independent_reviews_and_distinct_adjudicator_required')
        payload['review_hashes'] = sorted(fingerprint(r) for r in source)
        payload['adjudication'] = True
    payload['saved_at'] = stamp()
    target = review_path(directory, document['id'], payload['reviewer'], adjudication)
    if target.exists():
        previous = read(target)
        save(Path(directory) / 'history' / (fingerprint(previous) + '.json'), previous)
    save(target, payload)
    return target


def keys(items):
    return {(i['label'], i['start'], i['end']) for i in items}


def scores(predicted, gold):
    tp, fp, fn = len(predicted & gold), len(predicted - gold), len(gold - predicted)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    return {'tp': tp, 'fp': fp, 'fn': fn, 'precision': precision, 'recall': recall, 'f1': f1}


def evaluate(directory, single_reviewer=None):
    manifest, predictions = load_dataset(directory)
    criteria = read(Path(directory) / 'criteria.json')
    documents = manifest['documents']
    counts = Counter((d['court'], int(d['date'][:4])) for d in documents)
    missing = [{'court': court, 'year': year} for court in criteria['required_courts']
               for year in criteria['required_years'] if not counts[court, year]]
    result = {'dataset_id': Path(directory).name, 'created_at': stamp(), 'documents': len(documents),
              'target_documents': manifest['target_documents'], 'missing_court_year_strata': missing,
              'rules_version': predictions['rules_version'], 'scoring': 'exact-label-and-unicode-span; micro counts',
              'splits': {}, 'reviewed_documents': 0, 'adjudicated_documents': 0,
              'source_integrity': 'frozen-text-and-offsets-checked',
              'adoption_accuracy': None, 'adoption_reason': 'current_extractor_does_not_predict_adoption',
              'reviewer_agreement': {}, 'release': 'blocked', 'blockers': []}
    diagnostic = []
    grouped = {'development': [], 'test': []}
    agreements = {label: [set(), set()] for label in LABELS}
    for document in documents:
        if hashlib.sha256(document['text'].encode()).hexdigest() != document['text_sha256']:
            raise ValueError('frozen_text_hash_mismatch')
        reviews = reviews_for(directory, document)
        if reviews:
            result['reviewed_documents'] += 1
        if single_reviewer:
            own = next((r for r in reviews if r['reviewer'] == single_reviewer.strip().casefold()), None)
            if own:
                raw = predictions['documents'][document['id']]['annotations']
                predicted = {(label, segment['start'], segment['end']) for item in raw
                             for label in item['labels'] for segment in item['segments']}
                diagnostic.append((document['id'], predicted, keys(own['annotations'])))
        if len(reviews) >= 2:
            pair = sorted(reviews, key=lambda r: r['reviewer'])[:2]
            for n, row in enumerate(pair):
                for label, start, end in keys(row['annotations']):
                    agreements[label][n].add((document['id'], start, end))
        gold = reviews_for(directory, document, True)
        # An adjudication becomes stale if any completed independent review changes.
        hashes = sorted(fingerprint(r) for r in reviews)
        gold = [g for g in gold if g.get('review_hashes') == hashes]
        if len(gold) != 1:
            continue
        result['adjudicated_documents'] += 1
        raw = predictions['documents'][document['id']]['annotations']
        predicted = set()
        for item in raw:
            for segment in item['segments']:
                if document['text'][segment['start']:segment['end']] != segment['text']:
                    raise ValueError('prediction_quote_mismatch')
                for label in item['labels']:
                    predicted.add((label, segment['start'], segment['end']))
        grouped[document['split']].append((document['id'], predicted, keys(gold[0]['annotations'])))
    for split, rows in grouped.items():
        result['splits'][split] = {'adjudicated_documents': len(rows), 'labels': {}}
        for label in LABELS:
            p = {(doc, start, end) for doc, pred, _ in rows for lab, start, end in pred if lab == label}
            g = {(doc, start, end) for doc, _, gold in rows for lab, start, end in gold if lab == label}
            result['splits'][split]['labels'][label] = scores(p, g) if rows else None
    result['reviewer_agreement'] = {label: scores(*pair) for label, pair in agreements.items()}
    if single_reviewer:
        result['single_reviewer_diagnostic'] = {
            'reviewer': single_reviewer.strip().casefold(), 'documents': len(diagnostic),
            'status': 'diagnostic_only_not_independent_validation', 'labels': {}}
        for label in LABELS:
            p = {(doc, start, end) for doc, pred, _ in diagnostic for lab, start, end in pred if lab == label}
            g = {(doc, start, end) for doc, _, gold in diagnostic for lab, start, end in gold if lab == label}
            result['single_reviewer_diagnostic']['labels'][label] = scores(p, g) if diagnostic else None
    blockers = result['blockers']
    if len(documents) < criteria['minimum_documents']: blockers.append('insufficient_documents')
    if missing: blockers.append('missing_court_year_coverage')
    if not criteria['approval_reference']: blockers.append('criteria_not_human_approved')
    if not criteria.get('source_approval_reference'): blockers.append('source_eligibility_not_human_approved')
    if result['adjudicated_documents'] < len(documents): blockers.append('independent_reviews_and_adjudication_pending')
    test = result['splits']['test']
    if test['adjudicated_documents'] < criteria['minimum_test_documents']: blockers.append('insufficient_blind_test_documents')
    for label, metric in test['labels'].items():
        if not metric or metric['tp'] + metric['fn'] < criteria['minimum_gold_per_label_test']:
            blockers.append('insufficient_test_gold:' + label)
        elif (metric['precision'] or 0) < criteria['precision'] or (metric['recall'] or 0) < criteria['recall']:
            blockers.append('quality_threshold_not_met:' + label)
    # This engineering report can signal readiness for release review, never release production itself.
    if not blockers: result['release'] = 'eligible_for_human_release_review'
    output = 'diagnostic-' + document_key(single_reviewer.strip().casefold()) + '.json' if single_reviewer else 'evaluation.json'
    save(Path(directory) / output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'evaluate'))
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--single-reviewer', help='Optional single-reviewer diagnostic; cannot approve release')
    args = parser.parse_args()
    directory = args.directory
    try:
        if args.command == 'prepare':
            directory = prepare()
        directory = directory or Path(read(BASE / 'nlp-validation/current.json')['directory'])
        print(json.dumps({'directory': str(directory), 'evaluation': evaluate(directory, args.single_reviewer)}, ensure_ascii=False, indent=2))
    except (FileNotFoundError, ValueError) as exc:
        parser.exit(2, f'{exc}\n')


if __name__ == '__main__':
    main()
