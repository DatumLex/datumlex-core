"""FX115 fixtures are synthetic engineering oracles, never legal release evidence."""
import json
import os
from copy import deepcopy
from importlib import import_module
from pathlib import Path
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connection
from django.http import QueryDict
from django.test import Client, TestCase, TransactionTestCase, override_settings

from src.accounts.models import Court
from src.nlp.contracts import fingerprint
from src.nlp.extraction import annotation
from src.services import analytical_context as context
from src.services import nlp_dashboard as dashboard
from src.services import nlp_evidence as evidence
from tests.test_nlp_evidence import fixture, rehash


class DashboardTests(TransactionTestCase if connection.vendor == 'postgresql' else TestCase):
    def _fixture_teardown(self):
        if connection.vendor != 'postgresql':
            return super()._fixture_teardown()
        if not connection.settings_dict['NAME'].startswith('test_datumlex_'):
            raise RuntimeError('Refusing administrative teardown outside a disposable test database')
        tables = import_module('src.db.migrations.0011_nlp_history_guards').TABLES
        with connection.cursor() as cursor:
            for table in tables:
                cursor.execute(f'ALTER TABLE {table} DISABLE TRIGGER nlp_no_truncate')
        try:
            super()._fixture_teardown()
        finally:
            with connection.cursor() as cursor:
                for table in tables:
                    cursor.execute(f'ALTER TABLE {table} ENABLE TRIGGER nlp_no_truncate')

    def setUp(self):
        self.actor = get_user_model().objects.create_user(username='fx115-reviewer', role='Admin', approved=True)
        self.actor.courts.add(Court.objects.get_or_create(code='STJ', defaults={'name': 'STJ'})[0])
        self.client.force_login(self.actor)
        self.catalog = {}
        self.releases = {}
        self.source_text = 'Não houve nexo causal.'
        self.supplied = {'courts': ['STJ'], 'sources': ['stj_jurisprudence'], 'subject_codes': [10433],
                         'start': '2024-01-01', 'end': '2024-12-31'}

    def document(self, name='one', duplicate=False, approved=True):
        text = self.source_text + ('\n' + self.source_text if duplicate else '')
        result = fixture(text)
        key = f'STJ:FX115-{name}'
        result['document_id'] = key
        result['source']['document_id'] = key
        result['source']['source_url'] = 'https://www.stj.jus.br/synthetic-fixture'
        result['annotations'] = [annotation(text, ['LEGAL_THESIS', 'LEGAL_GROUND'],
                                            [(0, 22, text[:22])], 'model_replay')]
        if duplicate:
            result['annotations'].append(annotation(text, ['LEGAL_THESIS'], [(23, 45, text[23:45])], 'model_replay'))
        rehash(result)
        run = evidence.persist_result(result, text, request_key=uuid4())
        for row in run.evidences.all():
            if approved:
                evidence.review(evidence_id=row.pk, actor=self.actor, expected_revision=0, action='approve',
                                reason='FX115 synthetic review only', request_key=uuid4())
        self.releases['FX115-RELEASE'] = {'state': 'released', 'approval_reference': 'FX115-simulated-quality',
                                        'benchmark_version': 'FX115-synthetic-v1', 'rights_approval_reference': 'FX115-only',
                                        'pipeline_sha256': fingerprint(result['pipeline']), 'source': 'stj_jurisprudence',
                                        'inclusion_policy': 'human_approved_only', 'tasks': ['LEGAL_GROUND', 'LEGAL_THESIS']}
        self.catalog[key] = {'source': 'stj_jurisprudence', 'subject_codes': [10433, 10439],
                             'fixture_id': 'FX115-PERSISTED-01',
                             'decision_date': '2024-01-10', 'outcome': 'granted',
                             'extraction_id': str(run.pk), 'text_version_id': str(run.text_version_id),
                             'mapping_approval_reference': 'FX115-mapping-only', 'release_id': 'FX115-RELEASE'}
        return run

    def create(self):
        with override_settings(NLP_DASHBOARD_CATALOG=self.catalog, NLP_DASHBOARD_RELEASES=self.releases):
            return dashboard.create(self.actor, self.supplied)

    def test_canonical_identity_and_explicit_empty(self):
        supplied = self.supplied | {'sources': ['stj_jurisprudence', 'stj_jurisprudence']}
        self.assertEqual(context.identity(context.resolve(self.actor, supplied)), context.identity(context.resolve(self.actor, self.supplied)))
        self.assertEqual(context.from_query(self.actor, QueryDict('court[]='))['courts'], [])
        self.assertEqual(context.resolve(self.actor, {})['courts'], ['STJ'])

    def test_invalid_arrays_scalars_and_dates(self):
        for query in ['court=STJ', 'court[]=STJ&court[]=', 'subject=', 'start=2024-01-01&start=2024-01-02',
                      'court[]=STJ,TJDFT', 'start=2024-02-30', 'end=2099-01-01']:
            with self.subTest(query=query), self.assertRaises(ValueError):
                context.from_query(self.actor, QueryDict(query))

    def test_whole_selection_authorization(self):
        with self.assertRaises(PermissionError):
            context.resolve(self.actor, {'courts': ['STJ', 'TJDFT']})

    def test_no_quality_decision_never_fabricates_ranking(self):
        self.document()
        self.releases.clear()
        record = self.create()
        self.assertEqual(record.payload['status'], 'unavailable')
        self.assertEqual(record.payload['items'], [])
        self.assertEqual(record.payload['exclusions']['quality_blocked'], 1)

    def test_unmapped_source_is_disclosed(self):
        self.document()
        self.catalog.clear()
        record = self.create()
        self.assertEqual(record.payload['exclusions']['unmapped_documents'], 1)
        self.assertEqual(record.payload['items'], [])

    def test_hand_counted_documents_not_segments_or_subjects(self):
        self.document(duplicate=True)
        self.document('two')
        record = self.create()
        population = record.payload['populations']['decision_text']
        self.assertEqual(population['denominator'], 2)
        self.assertEqual(population['theses'][0]['document_count'], 2)
        self.assertEqual(population['theses'][0]['evidence_count'], 3)
        self.assertEqual(population['grounds'][0]['document_count'], 2)
        self.assertEqual(record.payload['data_mode'], 'fixture')

    def test_pending_is_not_human_approved(self):
        self.document(approved=False)
        record = self.create()
        self.assertEqual(record.payload['items'], [])
        self.assertEqual(record.payload['populations']['decision_text']['denominator'], 1)

    def test_outcomes_change_display_not_population(self):
        self.document()
        self.supplied['outcomes'] = ['denied']
        population = self.create().payload['populations']['decision_text']
        self.assertEqual(population['documents_in_scope'], 1)
        self.assertEqual(population['documents_quality_released'], 1)
        self.assertEqual(population['denominator'], 0)
        self.assertEqual(population['theses'], [])

    def test_no_matching_dates_and_empty_sources(self):
        self.document()
        self.supplied['start'] = '2024-02-01'
        self.assertEqual(self.create().payload['populations']['decision_text']['documents_in_scope'], 0)
        self.supplied['sources'] = []
        self.assertEqual(self.create().payload['status'], 'empty')

    def test_frozen_revision_and_exact_export(self):
        run = self.document()
        record = self.create()
        row = run.evidences.get()
        evidence.review(evidence_id=row.pk, actor=self.actor, expected_revision=1, action='reject',
                        reason='FX115 later review', request_key=uuid4())
        with override_settings(NLP_DASHBOARD_RELEASES=self.releases):
            response = self.client.get(f'/api/v2/analysis-snapshots/{record.pk}/export/')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['items'][0]['revision'], 1)
        self.assertEqual(payload['items'][0]['effective']['segments'][0]['text'], self.source_text)
        self.assertEqual(payload['query_id'], context.identity(payload['context']))
        self.assertEqual(payload['sha256'], fingerprint(record.payload))
        self.assertEqual(self.create().payload['items'], [])

    def test_report_uses_same_snapshot_passage_and_versions(self):
        self.document(duplicate=True)
        record = self.create()
        with override_settings(NLP_DASHBOARD_RELEASES=self.releases):
            response = self.client.get(f'/api/v2/analysis-snapshots/{record.pk}/report/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'FX115-PERSISTED-01')
        self.assertContains(response, record.sha256)
        self.assertContains(response, record.payload['query_id'])
        self.assertContains(response, self.source_text)
        self.assertContains(response, record.payload['items'][0]['text_version_id'])
        self.assertContains(response, 'Imprimir ou salvar em PDF')
        if directory := os.environ.get('NLP_REPORT_QA_DIR'):
            target = Path(directory)
            (target / 'report.html').write_bytes(response.content)
            (target / 'report-snapshot.json').write_text(json.dumps(dashboard.manifest(record, full=True), ensure_ascii=False), encoding='utf-8')

    def test_cursor_bound_to_population_snapshot_and_order(self):
        self.document(duplicate=True)
        record = self.create()
        group = record.payload['populations']['decision_text']['theses'][0]['id']
        first = dashboard.page(record, 'theses', QueryDict('limit=1'), group)
        self.assertIsNotNone(first['next_cursor'])
        query = QueryDict('', mutable=True)
        query.update({'limit': '1', 'cursor': first['next_cursor']})
        second = dashboard.page(record, 'theses', query, group)
        self.assertNotEqual(first['items'][0]['id'], second['items'][0]['id'])
        self.assertIsNone(second['next_cursor'])
        with self.assertRaises(ValueError):
            dashboard.page(self.create(), 'theses', query, group)
        with self.assertRaises(ValueError):
            dashboard.page(record, 'theses', QueryDict('cursor=forged'))

    def test_release_revocation_blocks_new_and_legacy_snapshot_reads(self):
        self.document()
        record = self.create()
        for route in [f'/api/v2/analysis-snapshots/{record.pk}/export/', f'/api/v1/evidence-snapshots/{record.pk}/']:
            self.assertEqual(self.client.get(route).status_code, 403)

    def test_authorization_revocation_and_owner(self):
        record = self.create()
        self.actor.courts.clear()
        with self.assertRaises(PermissionError):
            dashboard.read(self.actor, record.pk)
        other = get_user_model().objects.create_user(username='fx115-other', approved=True)
        with self.assertRaises(PermissionError):
            dashboard.read(other, record.pk)

    def test_expiration_requires_explicit_refresh(self):
        record = self.create()
        with override_settings(NLP_DASHBOARD_TTL_HOURS=-1), self.assertRaises(evidence.Conflict):
            dashboard.read(self.actor, record.pk)

    def test_api_options_snapshot_and_validation(self):
        response = self.client.get('/api/v2/filter-options/?court[]=STJ')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['context']['courts'], ['STJ'])
        response = self.client.post('/api/v2/analysis-snapshots/', json.dumps({'context': self.supplied}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('items', response.json())
        snapshot_id = response.json()['snapshot_id']
        self.assertEqual(self.client.get(f'/api/v2/analysis-snapshots/{snapshot_id}/theses/?limit=0').status_code, 400)
        self.assertEqual(self.client.get(f'/api/v2/analysis-snapshots/{snapshot_id}/theses/?order=score').status_code, 400)
        self.assertEqual(self.client.post('/api/v2/analysis-snapshots/', '{}', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.get('/api/v2/filter-options/?court[]=STJ&court[]=TJDFT').status_code, 403)

    def test_session_and_csrf(self):
        self.client.logout()
        self.assertEqual(self.client.get('/api/v2/filter-options/').status_code, 401)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.actor)
        self.assertEqual(client.post('/api/v2/analysis-snapshots/', '{}', content_type='application/json').status_code, 403)

    def test_official_link_rejects_scripts_and_lookalikes(self):
        for value in [None, 'javascript:alert(1)', 'https://stj.jus.br.evil.invalid/a', 'https://evil.invalid/stj.jus.br', 'http://stj.jus.br/a']:
            self.assertIsNone(dashboard.official_url(value))
        self.assertEqual(dashboard.official_url('https://processo.stj.jus.br/a'), 'https://processo.stj.jus.br/a')

    def test_pipeline_mismatch_blocks_output(self):
        self.document()
        self.releases['FX115-RELEASE']['pipeline_sha256'] = 'wrong'
        self.assertEqual(self.create().payload['items'], [])

    def test_literal_grouping_keeps_opposites_separate(self):
        run = self.document()
        item = evidence.read_evidence(run.evidences.get(), actor=self.actor)
        item['population'] = 'decision_text'
        other = deepcopy(item)
        other['id'] = str(uuid4())
        other['effective']['segments'][0]['text'] = 'Houve nexo causal.'
        self.assertEqual(len(dashboard.aggregate([item, other], 'decision_text', 'LEGAL_THESIS')), 2)
