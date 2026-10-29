"""Idempotent import of locally verified NLP outputs; no automatic legal approvals."""
import json
import argparse
from copy import deepcopy
import os
from pathlib import Path
import sys
from uuid import NAMESPACE_URL, uuid5, UUID

PROJECT = Path(__file__).resolve().parents[2]
BACKEND = PROJECT / 'backend'
ROOT = BACKEND / 'data/operations'
sys.path.insert(0, str(BACKEND))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')


def semantic_result(result):
    """A changed global queue alone is not a new extraction for an unchanged document."""
    value = deepcopy(result)
    value.pop('job_key', None)
    value.pop('result_sha256', None)
    value.get('pipeline', {}).pop('input_manifest_sha256', None)
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-id',type=UUID)
    args=parser.parse_args()
    output=ROOT/'nlp-local'/'jobs'/str(args.job_id) if args.job_id else ROOT/'nlp-local'
    import django
    django.setup()
    from django.conf import settings
    from src.nlp.adapters import read_source
    from src.nlp.contracts import fingerprint
    from src.services.nlp_evidence import persist_result
    from src.db.models import NlpExtraction
    config = settings.DATABASES['default']
    if config['ENGINE'] != 'django.db.backends.sqlite3' and config.get('HOST') not in ('localhost', '127.0.0.1', '::1'):
        raise RuntimeError('Local target required')
    queue = json.loads((output / 'queue.json').read_text(encoding='utf8'))
    expected = {row['document_id']: row['text_sha256'] for row in queue}
    count = unchanged = 0
    # The runner records its exact run directory; older experimental runs are not reimported.
    current = json.loads((output / 'current-run.json').read_text(encoding='utf8'))
    directory = Path(current['directory']).resolve()
    if not directory.is_relative_to((output / 'runs').resolve()):
        raise ValueError('Output directory outside local corpus')
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf8'))
    if fingerprint(manifest) != directory.name:
        raise ValueError('Manifest hash mismatch')
    for path in sorted(directory.rglob('*.json')):
        result = json.loads(path.read_text(encoding='utf8'))
        if 'result_sha256' not in result or result['pipeline'] != manifest:
            continue
        if expected.get(result['document_id']) != result['text'].get('sha256'):
            continue
        text = read_source(result['source'], ROOT) if result['status'] in ('completed', 'partial') else None
        expected_result = semantic_result(result)
        previous = NlpExtraction.objects.filter(document__source_key=result['document_id'],
            text_version__sha256=result['text']['sha256']).only('original_result')
        if any(semantic_result(old.original_result) == expected_result for old in previous):
            unchanged += 1
            continue
        persist_result(result, text, request_key=uuid5(NAMESPACE_URL, 'datumlex-local:' + result['result_sha256']))
        count += 1
    import io
    from django.core.management import call_command
    call_command('refresh_legal_corpus', category='jurisprudence', stdout=io.StringIO())
    print(json.dumps({'imported_or_verified': count, 'unchanged_skipped': unchanged, 'review_status': 'pending'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
