"""Persistence contract tests. Fixtures are synthetic, not legal quality evidence."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from importlib import import_module
from pathlib import Path
from threading import Barrier
from unittest import skipUnless
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase

from src.accounts.models import Court
from src.db.models import NlpEvidence, NlpRevision, NlpTextVersion
from src.nlp.adapters import read_source
from src.nlp.contracts import bytes_hash, fingerprint
from src.nlp.extraction import annotation
from src.services import nlp_evidence as service


def fixture(text='Não houve nexo causal. 😀', version='1'):
    item = annotation(text, ['CASE_HOLDING'], [(0, 22, text[:22])], 'model_replay')
    result = {
        'schema_version': '0.1.0', 'document_id': 'STJ:synthetic-114', 'source_version': version,
        'source': {'document_id': 'STJ:synthetic-114', 'court': 'STJ', 'source_version': version,
                   'source_url': 'https://example.invalid/synthetic', 'artifact_sha256': bytes_hash(text.encode())},
        'pipeline': {'rules_version': version, 'schema_version': '0.1.0'},
        'text': {'sha256': bytes_hash(text.encode()), 'offset_unit': 'unicode_code_point', 'normalization': 'identity-v1'},
        'status': 'completed', 'annotations': [item], 'relations': [], 'errors': [],
        'warnings': ['synthetic'], 'coverage': {'semantic_validation': 'not_performed'},
        'review': {'status': 'pending'}, 'evaluation': {'status': 'not_evaluated'},
    }
    result['result_sha256'] = fingerprint(result)
    return result


def rehash(result):
    result['result_sha256'] = fingerprint({k: v for k, v in result.items() if k != 'result_sha256'})
    return result


class EvidenceTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username='reviewer114', role='Admin', approved=True)
        self.actor.courts.add(Court.objects.get(pk='STJ'))
        self.text = 'Não houve nexo causal. 😀'
        self.result = fixture(self.text)
        self.run = service.persist_result(self.result, self.text, request_key=uuid4())
        self.evidence = self.run.evidences.get()

    def review(self, **kwargs):
        defaults = dict(actor=self.actor, expected_revision=0, action='approve', reason='Checked source', request_key=uuid4())
        defaults.update(kwargs)
        return service.review(self.evidence.pk, **defaults)

    def test_original_correction_and_history(self):
        corrected = deepcopy(self.evidence.original)
        corrected['labels'] = ['LEGAL_GROUND']
        revision = self.review(action='correct', replacement=corrected)
        self.review(expected_revision=1)
        self.assertEqual(service.read_evidence(self.evidence, actor=self.actor, original=True)['effective'], self.evidence.original)
        self.assertEqual(service.read_evidence(self.evidence, actor=self.actor, revision=1)['review_status'], 'corrected')
        current = service.read_evidence(self.evidence, actor=self.actor)
        self.assertEqual(current['effective'], corrected)
        self.assertEqual(current['review_status'], 'approved')
        self.assertTrue(current['has_corrections'])
        self.assertEqual(revision.reviewer_id, self.actor.pk)
        self.assertIsNotNone(revision.created_at)
        self.evidence.refresh_from_db()
        self.assertEqual(self.evidence.sha256, fingerprint(self.evidence.original))

    def test_review_idempotency_and_stale_write(self):
        key = uuid4()
        first = self.review(request_key=key)
        self.assertEqual(self.review(request_key=key).pk, first.pk)
        with self.assertRaises(service.Conflict):
            self.review(request_key=key, reason='different')
        with self.assertRaises(service.Conflict):
            self.review()
        self.assertEqual(NlpRevision.objects.count(), 1)

    def test_reject_reopen_and_illegal_transition(self):
        self.review(action='reject')
        with self.assertRaises(ValueError):
            self.review(expected_revision=1)
        self.review(expected_revision=1, action='reopen')
        self.assertEqual(service.read_evidence(self.evidence, actor=self.actor)['review_status'], 'pending')

    def test_invalid_span_and_missing_field_are_controlled(self):
        for mutate in ('offset', 'missing'):
            corrected = deepcopy(self.evidence.original)
            if mutate == 'offset':
                corrected['segments'][0]['end'] = 21
            else:
                del corrected['segments'][0]['text']
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                self.review(action='correct', replacement=corrected)
        self.assertEqual(NlpRevision.objects.count(), 0)

    def test_confidence_and_identity_cannot_be_rewritten(self):
        corrected = deepcopy(self.evidence.original)
        corrected['confidence']['score'] = 1
        with self.assertRaises(ValueError):
            self.review(action='correct', replacement=corrected)

    def test_ingest_idempotency_and_checksum(self):
        key = uuid4()
        first = service.persist_result(self.result, self.text, request_key=key)
        second = service.persist_result(self.result, self.text, request_key=key)
        self.assertEqual(first.pk, second.pk)
        bad = deepcopy(self.result)
        bad['pipeline']['rules_version'] = '2'
        with self.assertRaises(ValueError):
            service.persist_result(bad, self.text, request_key=uuid4())
        with self.assertRaises(service.Conflict):
            service.persist_result(rehash(bad), self.text, request_key=key)

    def test_reprocess_and_changed_text_do_not_inherit_reviews(self):
        self.review()
        text = self.text + ' Novo parágrafo.'
        new = service.persist_result(fixture(text, '2'), text, request_key=uuid4(), previous_id=self.run.pk, reason='Changed source')
        self.assertEqual(NlpTextVersion.objects.count(), 2)
        self.assertEqual(new.previous_id, self.run.pk)
        self.assertEqual(new.evidences.get().revisions.count(), 0)
        self.assertEqual(self.run.original_result, self.result)
        self.assertEqual(service.read_evidence(new.evidences.get(), actor=self.actor)['review_status'], 'pending')

    def test_source_removed_and_unavailable_preserve_text(self):
        for state in ('changed', 'not_found', 'removed', 'temporarily_unavailable'):
            service.observe_source(self.run.document_id, state=state, details={'synthetic': True})
            value = service.read_evidence(self.evidence, actor=self.actor)
            self.assertEqual(value['source_state'], state)
            self.assertEqual(value['original'], self.evidence.original)
        self.assertEqual(self.run.text_version.text, self.text)

    def test_missing_text_is_not_empty_success(self):
        result = deepcopy(self.result)
        result.update(status='missing_text', annotations=[], errors=[{'reason': 'missing_text'}])
        run = service.persist_result(rehash(result), None, request_key=uuid4())
        self.assertIsNone(run.text_version)
        self.assertEqual(run.evidences.count(), 0)
        self.assertEqual(run.status, 'missing_text')

    def test_snapshot_freezes_revision_and_source_state(self):
        frozen = service.snapshot(actor=self.actor, evidence_ids=[str(self.evidence.pk)], context={'court': ['STJ']})
        self.review()
        service.observe_source(self.run.document_id, state='removed')
        frozen.refresh_from_db()
        self.assertEqual(frozen.sha256, fingerprint(frozen.payload))
        self.assertEqual(frozen.payload['items'][0]['revision'], 0)
        self.assertEqual(frozen.payload['items'][0]['source_state'], 'available')
        self.actor.courts.clear()
        with self.assertRaises(PermissionError):
            service.read_snapshot(frozen, self.actor)

    def test_permissions_enforced_on_service(self):
        self.actor.role = 'Padrão'
        with self.assertRaises(PermissionError):
            self.review()
        self.actor.courts.clear()
        with self.assertRaises(PermissionError):
            service.read_evidence(self.evidence, actor=self.actor)

    def test_database_blocks_update_and_delete(self):
        for operation in ('update', 'delete'):
            with self.subTest(operation=operation), self.assertRaises(DatabaseError), transaction.atomic():
                if operation == 'update':
                    NlpEvidence.objects.filter(pk=self.evidence.pk).update(original={})
                else:
                    NlpEvidence.objects.filter(pk=self.evidence.pk).delete()

    @skipUnless(connection.vendor == 'postgresql', 'PostgreSQL trigger')
    def test_database_rejects_invalid_revision_chain(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            NlpRevision.objects.create(evidence=self.evidence, number=2, action='approve', state='approved',
                                       reviewer=self.actor, reason='invalid gap', before=self.evidence.original,
                                       after=self.evidence.original, request_key=uuid4(), request_sha256='0' * 64)

    @skipUnless(connection.vendor == 'postgresql', 'PostgreSQL trigger')
    def test_database_blocks_truncate(self):
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute('TRUNCATE warehouse_nlpevidence CASCADE')

    def test_api_original_review_and_snapshot(self):
        url = f'/api/v1/evidences/{self.evidence.pk}/'
        self.assertEqual(self.client.get(url).status_code, 401)
        self.client.force_login(self.actor)
        self.assertEqual(self.client.get(url + '?view=original').json()['original'], self.evidence.original)
        response = self.client.post(url + 'revisions/', {'expected_revision': 0, 'action': 'approve', 'reason': 'Checked'},
                                    content_type='application/json', HTTP_IDEMPOTENCY_KEY=str(uuid4()))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.client.get(url).json()['review_status'], 'approved')
        history = self.client.get(url + 'revisions/').json()
        self.assertEqual(len(history['items']), 1)
        response = self.client.post('/api/v1/evidence-snapshots/',
                                    {'evidence_ids': [str(self.evidence.pk)], 'context': {}}, content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        snapshot_id = response.json()['id']
        self.assertEqual(self.client.get(f'/api/v1/evidence-snapshots/{snapshot_id}/').json()['sha256'], response.json()['sha256'])

    def test_api_extraction_and_pagination_scope(self):
        self.client.force_login(self.actor)
        url = f'/api/v1/extractions/{self.run.pk}/'
        self.assertEqual(self.client.get(url).json()['original_result'], self.result)
        page = self.client.get(url + 'evidences/?limit=1').json()
        self.assertEqual(page['total'], 1)
        self.assertEqual(page['items'][0]['id'], str(self.evidence.pk))
        self.assertIsNone(page['next_after'])
        self.actor.courts.clear()
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_api_review_requires_csrf(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.actor)
        response = client.post(f'/api/v1/evidences/{self.evidence.pk}/revisions/',
                               {'action': 'approve'}, content_type='application/json')
        self.assertEqual(response.status_code, 403)

    def test_api_stale_review_and_invalid_request(self):
        self.client.force_login(self.actor)
        self.review()
        url = f'/api/v1/evidences/{self.evidence.pk}/revisions/'
        response = self.client.post(url, {'expected_revision': 0, 'action': 'approve', 'reason': 'Checked'},
                                    content_type='application/json', HTTP_IDEMPOTENCY_KEY=str(uuid4()))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.post(url, {}, content_type='application/json').status_code, 400)

    @skipUnless(os.environ.get('NLP_REAL_ROOT'), 'Optional local #109 outputs')
    def test_real_pipeline_outputs_reconcile(self):
        root = Path(os.environ['NLP_REAL_ROOT']).resolve()
        counts = {}
        annotations = 0
        for path in sorted((root / 'output/task-109').rglob('*.json')):
            result = json.loads(path.read_text(encoding='utf-8'))
            if 'result_sha256' not in result or 'annotations' not in result:
                continue
            text = read_source(result['source'], root) if result['status'] in ('completed', 'partial') else None
            run = service.persist_result(result, text, request_key=uuid4())
            self.assertEqual(run.original_result, result)
            self.assertEqual(run.evidences.count(), len(result['annotations']))
            if text is not None:
                self.assertEqual(run.text_version.text, text)
            for evidence in run.evidences.all():
                self.assertEqual(evidence.sha256, fingerprint(evidence.original))
            court = result['source']['court']
            counts[court] = counts.get(court, 0) + 1
            annotations += len(result['annotations'])
        self.assertEqual(set(counts), {'TJDFT', 'STJ'})
        self.assertGreater(annotations, 0)
        print(f'REAL_RECONCILIATION documents={counts} annotations={annotations}')


@skipUnless(connection.vendor == 'postgresql', 'Requires actual PostgreSQL row locks')
class ConcurrentReviewTests(TransactionTestCase):
    def _fixture_teardown(self):
        # ONLY the disposable Django test database: its administrative teardown
        # must deliberately bypass TRUNCATE guards to clean committed fixtures.
        if not connection.settings_dict['NAME'].startswith('test_'):
            raise RuntimeError('Refusing cleanup outside a test database')
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

    def test_two_reviewers_cannot_overwrite_same_revision(self):
        actor = get_user_model().objects.create_user(username='concurrent114', role='Admin', approved=True)
        court, _ = Court.objects.get_or_create(code='STJ', defaults={'name': 'STJ'})
        actor.courts.add(court)
        text = 'Não houve nexo causal. 😀'
        evidence = service.persist_result(fixture(text), text, request_key=uuid4()).evidences.get()
        barrier = Barrier(2)

        def attempt():
            try:
                reviewer = get_user_model().objects.get(pk=actor.pk)
                barrier.wait(timeout=10)
                service.review(evidence.pk, actor=reviewer, expected_revision=0, action='approve',
                               reason='Concurrent review', request_key=uuid4())
                return 'accepted'
            except service.Conflict:
                return 'conflict'
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt) for _ in range(2)]
            outcomes = [future.result(timeout=20) for future in futures]
        self.assertCountEqual(outcomes, ['accepted', 'conflict'])
        self.assertEqual(evidence.revisions.count(), 1)
