"""Synthetic cases run only in the isolated test database, never the exported corpus."""
from io import BytesIO
from uuid import uuid4

from django.test import TestCase
from pypdf import PdfReader

from src.services.nlp_evidence import persist_result
from src.services.report_nlp import report_nlp
from tests.access_helpers import authorize_data
from tests.test_nlp_evidence import fixture, rehash


class ReportNlpTests(TestCase):
    scope = dict(court='TJDFT', subject=None, start='2024-01-01', end='2024-12-31')

    def document(self, key, day=None, court='TJDFT', subject_codes=None, version='1'):
        result = fixture(version=version)
        result['document_id'] = key
        result['source'].update(document_id=key, court=court, decision_date=day,
                                subject_codes=subject_codes or [])
        rehash(result)
        return persist_result(result, 'Não houve nexo causal. 😀', request_key=uuid4())

    def test_unique_latest_documents_dates_courts_and_subjects(self):
        self.document('TJDFT:one', '2024-05-01', subject_codes=[10433])
        self.document('TJDFT:one', '2024-05-01', subject_codes=[10433], version='2')
        self.document('TJDFT:undated')
        self.document('TJDFT:outside', '2020-01-01')
        self.document('STJ:hidden', '2024-05-01', court='STJ')
        counts = report_nlp(self.scope)
        self.assertEqual(counts['processed'], 3)
        self.assertEqual((counts['in_period'], counts['undated'], counts['outside_period']), (1, 1, 1))
        self.assertEqual(counts['released'], 0)
        counts = report_nlp(self.scope | {'subject': 10433})
        self.assertEqual(counts['in_period'], 1)
        self.assertEqual(counts['subject_unconfirmed'], 2)

    def test_pdf_reports_processing_without_claiming_legal_review(self):
        authorize_data(self.client)
        self.document('TJDFT:pending', '2024-05-01')
        response = self.client.get('/api/report.pdf/?court=TJDFT&start=2024-01-01&end=2024-12-31')
        self.assertEqual(response.status_code, 200)
        pages = PdfReader(BytesIO(response.content)).pages
        text = ' '.join(' '.join(page.extract_text() for page in pages).split())
        self.assertIn('Documentos processados por NLP', text)
        self.assertIn('1 documentos processados nos tribunais selecionados', text)
        self.assertIn('Referências a precedentes', text)
        self.assertIn('0 documentos liberados e 0 evidências aprovadas', text)
        self.assertNotIn('Requer snapshot de evidências revisadas', text)
        self.assertEqual(len(pages), 5)

    def test_fixture_marked_catalog_is_never_counted(self):
        self.document('TJDFT:fixture', '2024-05-01')
        with self.settings(NLP_DASHBOARD_CATALOG={'TJDFT:fixture': {'fixture_id': 'TEST-ONLY'}}):
            self.assertEqual(report_nlp(self.scope)['processed'], 0)
