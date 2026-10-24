"""Loopback-only FX115 demo: actual extractor/API, separate synthetic SQLite DB."""
import os
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

from django.conf import settings  # noqa: E402

target = BACKEND.parents[1] / 'output' / 'task-115-demo'
target.mkdir(parents=True, exist_ok=True)
# Override BEFORE django.setup(): never provision/write the normal warehouse.
settings.DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': target / 'synthetic.sqlite3'}}
settings.DEBUG = True
settings.ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
settings.SESSION_COOKIE_NAME = 'datumlex_fx115_demo_session'
settings.CSRF_COOKIE_NAME = 'datumlex_fx115_demo_csrf'
settings.SESSION_COOKIE_SECURE = False
settings.CSRF_COOKIE_SECURE = False
settings.CSRF_TRUSTED_ORIGINS = ['http://127.0.0.1:5180', 'http://localhost:5180']
os.environ.pop('DATUMLEX_SUPPORT_PASSWORD', None)

import django  # noqa: E402

django.setup()
from django.contrib.auth import get_user_model  # noqa: E402
from django.core.management import call_command  # noqa: E402

from src.accounts.models import Court  # noqa: E402
from src.nlp.contracts import bytes_hash, fingerprint  # noqa: E402
from src.nlp.extraction import extract  # noqa: E402
from src.services import nlp_evidence  # noqa: E402

call_command('migrate', interactive=False, verbosity=0)
actor, created = get_user_model().objects.get_or_create(username='fx115-demo', defaults={
    'name': 'Demonstração Sintética', 'email': 'fx115-demo@example.invalid', 'approved': True, 'role': 'Admin'})
if created:
    actor.set_password('FX115-local-demo-only')
    actor.save()
actor.courts.add(Court.objects.get_or_create(code='STJ', defaults={'name': 'STJ'})[0])

texts = [
    'O dever de indenizar exige nexo causal porque o dano deve decorrer da conduta.',
    'O dever de indenizar exige nexo causal porque o dano deve decorrer da conduta.',
    'A responsabilidade civil depende de prova, pois a culpa exclusiva afasta o nexo causal.',
]
catalog = {}
pipeline = {'rules_version': '0.1.0', 'schema_version': '0.1.0', 'execution': 'FX115-DEMO-real-rule-extractor'}
for index, text in enumerate(texts, 1):
    key = f'STJ:FX115-DEMO-{index:02}'
    annotations, skipped = extract(text)
    result = {'schema_version': '0.1.0', 'document_id': key, 'source_version': 'FX115-DEMO-v1',
              'source': {'document_id': key, 'court': 'STJ', 'source_version': 'FX115-DEMO-v1',
                         'source_url': None, 'artifact_sha256': bytes_hash(text.encode('utf-8'))},
              'pipeline': pipeline,
              'text': {'sha256': bytes_hash(text.encode('utf-8')), 'offset_unit': 'unicode_code_point', 'normalization': 'identity-v1'},
              'status': 'completed', 'annotations': annotations, 'relations': [], 'errors': [],
              'warnings': ['FX115-DEMO: synthetic document; no official source; review and release are simulated'],
              'coverage': {'input_characters': len(text), 'skipped_paragraphs': skipped, 'semantic_validation': 'not_performed'},
              'review': {'status': 'pending'}, 'evaluation': {'status': 'not_evaluated'}}
    result['result_sha256'] = fingerprint(result)
    run = nlp_evidence.persist_result(result, text, request_key=uuid5(NAMESPACE_URL, key + ':v1'))
    for row in run.evidences.all():
        if not row.revisions.exists():
            nlp_evidence.review(evidence_id=row.pk, actor=actor, expected_revision=0, action='approve',
                                reason='FX115 DEMO ONLY: simulated review; not legal approval',
                                request_key=uuid5(NAMESPACE_URL, str(row.pk) + ':demo-review'))
    catalog[key] = {'source': 'stj_jurisprudence', 'subject_codes': [10433], 'decision_date': '2024-01-10',
                    'outcome': 'denied' if index == 3 else 'granted', 'title': f'Documento sintético {index} — FX115-DEMO',
                    'extraction_id': str(run.pk), 'text_version_id': str(run.text_version_id),
                    'mapping_approval_reference': 'SIMULATED-FX115-DEMO', 'release_id': 'FX115-DEMO', 'fixture_id': 'FX115-DEMO'}
    print(f'{key}: actual extract() generated {len(annotations)} annotations', flush=True)

settings.NLP_DASHBOARD_CATALOG = catalog
settings.NLP_DASHBOARD_RELEASES = {'FX115-DEMO': {
    'state': 'released', 'approval_reference': 'SIMULATED-FX115-DEMO', 'benchmark_version': 'synthetic-only',
    'rights_approval_reference': 'synthetic-texts-only', 'pipeline_sha256': fingerprint(pipeline),
    'source': 'stj_jurisprudence', 'inclusion_policy': 'human_approved_only', 'tasks': ['LEGAL_GROUND', 'LEGAL_THESIS']}}
print(f'FX115 DEMO ONLY — database: {target / "synthetic.sqlite3"}', flush=True)
call_command('runserver', '127.0.0.1:8015', use_reloader=False)
