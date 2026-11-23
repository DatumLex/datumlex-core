import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from src.db.models import LegalNarrativeDraft
from src.services import legal_chat as chat
from tests import test_nlp_dashboard as fixtures


class LegalChatTests(fixtures.DashboardTests):
    # Snapshot creation sets transaction isolation before querying PostgreSQL.
    # Reuse the real transactional fixtures and their guarded disposable-DB cleanup.

    def prepare(self):
        cache.clear()
        self.document()
        record = self.create()
        self.record = record
        self.item = record.payload['items'][0]
        self.answer = {'status': 'draft', 'facts': [{'evidence_id': self.item['id'], 'quote': self.source_text}],
            'interpretations': [{'text': 'O trecho registra ausência de nexo; o alcance depende de revisão.', 'evidence_ids': [self.item['id']]}],
            'uncertainties': ['Corpus parcial.']}
        return override_settings(NLP_DASHBOARD_RELEASES=self.releases, NLP_DASHBOARD_CATALOG=self.catalog)

    def generate(self):
        return self.client.post(f'/api/v2/analysis-snapshots/{self.record.pk}/chat/',
            data=json.dumps({'question': 'Quais fundamentos constam das fontes?', 'consent': True}), content_type='application/json')

    def test_generate_review_approve_and_export_same_context(self):
        with self.prepare(), patch.object(chat, 'invoke', return_value=(self.answer, {'totalTokenCount': 42}, 'test-model')) as provider:
            response = self.generate()
            self.assertEqual(response.status_code, 200, response.content)
            result = response.json()
            draft_id = result['draft_id']
            self.assertEqual(result['snapshot_sha256'], self.record.sha256)
            self.assertEqual(result['context'], self.record.payload['context'])
            self.assertEqual(result['status'], 'draft')
            self.assertEqual(provider.call_args.args[0], self.record.payload['context'])
            endpoint = f'/api/v2/legal-drafts/{draft_id}/'
            self.assertEqual(self.client.get(endpoint + 'export/').status_code, 409)
            approval = {'expected_sha256': result['sha256'], 'conclusions': 'Análise própria: ação, órgão e §.', 'confirmed': False}
            self.assertEqual(self.client.post(endpoint, data=json.dumps(approval), content_type='application/json').status_code, 400)
            approval['confirmed'] = True
            approved = self.client.post(endpoint, data=json.dumps(approval), content_type='application/json')
            self.assertEqual(approved.status_code, 200)
            self.assertEqual(approved.json()['status'], 'approved')
            exported = self.client.get(endpoint + 'export/')
            self.assertEqual(exported.status_code, 200)
            self.assertEqual(json.loads(exported.content)['user_conclusions'], approval['conclusions'])
            self.assertEqual(self.client.post(endpoint, data=json.dumps(approval), content_type='application/json').status_code, 400)

    def test_no_evidence_never_calls_provider(self):
        cache.clear()
        record = self.create()
        with patch.object(chat, 'invoke') as provider:
            with self.assertRaisesMessage(ValueError, 'Não há trechos'):
                chat.generate(self.actor, record.pk, 'Analisar pesquisa', True)
            provider.assert_not_called()

    def test_invalid_parent_is_a_controlled_error_without_provider_call(self):
        with self.prepare(), patch.object(chat, 'invoke') as provider:
            response = self.client.post(f'/api/v2/analysis-snapshots/{self.record.pk}/chat/',
                data=json.dumps({'question': 'Analisar pesquisa', 'consent': True, 'parent_id': 'invalid'}),
                content_type='application/json')
            self.assertEqual(response.status_code, 400)
            provider.assert_not_called()

    def test_bad_citation_and_conflict_are_blocked_without_draft(self):
        with self.prepare():
            for change in ({'facts': [{'evidence_id': self.item['id'], 'quote': 'Inventado'}]}, {'status': 'conflicting'}, {'status': 'insufficient'},
                           {'interpretations': [{'text': 'Inventado', 'evidence_ids': ['fake']}]}):
                cache.clear()
                with patch.object(chat, 'invoke', return_value=(self.answer | change, {}, 'test-model')):
                    self.assertEqual(self.generate().status_code, 400)
            self.assertEqual(LegalNarrativeDraft.objects.count(), 0)

    def test_access_revocation_and_explicit_consent(self):
        with self.prepare(), patch.object(chat, 'invoke', return_value=(self.answer, {}, 'test-model')) as provider:
            with self.assertRaises(ValueError):
                chat.generate(self.actor, self.record.pk, 'Analisar pesquisa', False)
            provider.assert_not_called()
            result = self.generate().json()
            self.actor.courts.clear()
            self.assertEqual(self.client.get(f"/api/v2/legal-drafts/{result['draft_id']}/").status_code, 403)
        self.client.logout()
        self.assertEqual(self.generate().status_code, 401)

    def test_throttling_and_new_version(self):
        with self.prepare(), patch.object(chat, 'invoke', return_value=(self.answer, {}, 'test-model')):
            first = self.generate().json()
            self.assertEqual(self.generate().status_code, 503)
            cache.clear()
            second = chat.generate(self.actor, self.record.pk, 'Regenerar análise', True, first['draft_id'])
            self.assertNotEqual(str(second.pk), first['draft_id'])
            self.assertEqual(str(second.parent_id), first['draft_id'])

    def test_release_revoked_during_generation(self):
        with self.prepare():
            def revoke(*args):
                self.releases.clear()
                return self.answer, {}, 'test-model'
            with patch.object(chat, 'invoke', side_effect=revoke):
                self.assertEqual(self.generate().status_code, 403)
            self.assertEqual(LegalNarrativeDraft.objects.count(), 0)


class ChatProviderTests(SimpleTestCase):
    @override_settings(GEMINI_API_KEY='')
    def test_missing_key_does_not_send(self):
        with patch.object(chat, 'urlopen') as send:
            with self.assertRaises(chat.ChatUnavailable):
                chat.invoke({}, 'Pergunta', [])
            send.assert_not_called()

    @override_settings(GEMINI_API_KEY='synthetic-key', GEMINI_MODEL='test-model')
    def test_provider_request_and_utf8(self):
        payload = {'status': 'insufficient', 'facts': [], 'interpretations': [], 'uncertainties': ['Órgão']}
        response = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(payload)}]}}], 'usageMetadata': {'totalTokenCount': 10}}
        with patch.object(chat, 'urlopen') as send:
            send.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode('utf-8')
            result, usage, model = chat.invoke({'assunto': 'ação'}, 'Órgão?', [])
            self.assertEqual(result, payload)
            request = send.call_args.args[0]
            self.assertNotIn('synthetic-key', request.full_url)
            self.assertIn('Órgão?', request.data.decode('utf-8'))
            self.assertEqual(usage['totalTokenCount'], 10)
            self.assertEqual(model, 'test-model')

    def test_validate_accepts_nonbreaking_space_literal_quote(self):
        retrieved = [{
            'id': 'ev-1',
            'passages': ['A restituição em dobro\xa0pressupõe a cobrança indevida e a ausência de engano justificável.'],
        }]
        output = {
            'status': 'draft',
            'facts': [{'evidence_id': 'ev-1', 'quote': 'A restituição em dobro pressupõe a cobrança indevida'}],
            'interpretations': [{'text': 'A devolução em dobro exige cobrança indevida.', 'evidence_ids': ['ev-1']}],
            'uncertainties': ['Recorte limitado à amostra revisada.'],
        }
        validated = chat.validate(output, retrieved)
        self.assertEqual(validated['status'], 'draft')
        self.assertEqual(len(validated['facts']), 1)
        self.assertEqual(len(validated['interpretations']), 1)
        self.assertEqual(len(validated['uncertainties']), 1)

    def test_validate_blocks_paraphrased_quote(self):
        retrieved = [{'id': 'ev-1', 'passages': ['A restituição em dobro pressupõe cobrança indevida.']}]
        output = {
            'status': 'draft',
            'facts': [{'evidence_id': 'ev-1', 'quote': 'Trecho inventado que não consta no acórdão'}],
            'interpretations': [],
            'uncertainties': [],
        }
        with self.assertRaises(ValueError):
            chat.validate(output, retrieved)
