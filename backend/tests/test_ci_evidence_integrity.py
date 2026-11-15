"""Synthetic source-fidelity regressions; no legal-quality claims."""
from copy import deepcopy
from uuid import uuid4

from django.test import TestCase

from src.db.models import NlpDocument, NlpEvidence, NlpExtraction, NlpTextVersion
from src.services.nlp_evidence import persist_result
from tests.test_nlp_evidence import fixture, rehash


class SourceFidelityTests(TestCase):
    def test_invalid_source_fidelity_is_rejected_before_any_write(self):
        text = 'Não houve nexo causal. 😀'
        for field in ('quote', 'offset', 'document', 'hash'):
            result = deepcopy(fixture(text))
            if field == 'quote':
                result['annotations'][0]['segments'][0]['text'] = 'Trecho inventado'
            elif field == 'offset':
                result['annotations'][0]['segments'][0]['start'] = 1
            elif field == 'document':
                result['source']['document_id'] = 'STJ:another-document'
            else:
                result['text']['sha256'] = '0' * 64
            with self.subTest(field=field), self.assertRaises(ValueError):
                persist_result(rehash(result), text, request_key=uuid4())
            for model in (NlpDocument, NlpTextVersion, NlpExtraction, NlpEvidence):
                self.assertEqual(model.objects.count(), 0)

    def test_changed_version_keeps_each_quote_attached_to_its_own_source(self):
        old_text = 'Não houve nexo causal. 😀'
        new_text = old_text + ' Nova versão da fonte.'
        old = persist_result(fixture(old_text, '1'), old_text, request_key=uuid4())
        new = persist_result(fixture(new_text, '2'), new_text, request_key=uuid4(),
                             previous_id=old.pk, reason='Updated source text')
        self.assertNotEqual(old.text_version_id, new.text_version_id)
        self.assertEqual(new.previous_id, old.pk)
        self.assertEqual(NlpTextVersion.objects.count(), 2)
        for run, expected_text, version in ((old, old_text, '1'), (new, new_text, '2')):
            self.assertEqual(run.text_version.text, expected_text)
            self.assertEqual(run.text_version.source['source_version'], version)
            self.assertEqual(run.text_version.document_id, run.document_id)
            for evidence in run.evidences.all():
                for segment in evidence.original['segments']:
                    self.assertEqual(expected_text[segment['start']:segment['end']], segment['text'])
