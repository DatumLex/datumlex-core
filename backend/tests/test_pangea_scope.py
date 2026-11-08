"""Offline tests for court boundaries, provenance and Pangea pagination."""
import io
import json
from unittest.mock import patch
from django.test import SimpleTestCase, TestCase
from django.core.management import call_command
from django.core.management.base import CommandError
from src.api.pangea_client import PangeaPublicSearchClient, PangeaError
from src.api.pangea_scope import selected_courts, public_judicial_url
from src.db.models import LegalReference, PangeaImportRun
from src.services.pangea_report import report_references

CATALOG = {'versao': 'test', 'orgaos': [{'sigla': code} for code in
    ('STJ','TJDF','TJSP','TJMG','TJRJ','TJRS','TJPR','TRF01','TRF03','TST')],
    'especies': [{'sigla': 'SUM'}, {'sigla': 'IRDR'}]}

def row(court, identifier='ref-1'):
    return {'id': identifier, 'orgao': court, 'tipo': 'SUM', 'nr': 1,
            'tese': 'Responsabilidade civil', 'ultimaAtualizacao': '01/01/2026',
            'processosParadigma': [{'numero': '123', 'link': 'https://www.tjsp.jus.br/processo'}]}

class PangeaClientScopeTests(SimpleTestCase):
    @patch('src.api.pangea_client.PangeaClient._read_json')
    def test_all_ten_use_actual_source_aliases(self, read):
        client = PangeaPublicSearchClient()
        client._catalog = CATALOG
        read.return_value = {'total': 1, 'resultados': [row('TJDF')]}
        result = client.search_page('responsabilidade civil', 0, 100)
        request = read.call_args.args[0]
        query = json.loads(request.data)['filtro']
        self.assertEqual(set(query['orgaos']), {x['sigla'] for x in CATALOG['orgaos']})
        self.assertEqual(query['pagina'], 1)
        self.assertEqual(result['resultados'][0]['orgao'], 'TJDF')

    @patch('src.api.pangea_client.PangeaClient._read_json')
    def test_out_of_scope_row_is_explicit_failure(self, read):
        client = PangeaPublicSearchClient()
        client._catalog = CATALOG
        read.return_value = {'total': 1, 'resultados': [row('STF')]}
        with self.assertRaises(PangeaError):
            client.search_page('responsabilidade civil', 0, 100, courts=['TJSP'])

    def test_missing_court_and_invalid_selection_are_rejected(self):
        client = PangeaPublicSearchClient()
        client._catalog = {**CATALOG, 'orgaos': [{'sigla': 'STJ'}]}
        with self.assertRaises(PangeaError):
            client.search_page('responsabilidade civil', 0, 100, courts=['TJSP'])
        with self.assertRaises(ValueError):
            selected_courts('STF')
        self.assertEqual(selected_courts('TJDF,TRF01,TRF03'), ('TJDFT','TRF1','TRF3'))

    def test_links_keep_public_judicial_hosts_only(self):
        self.assertTrue(public_judicial_url('https://www.tjsp.jus.br/processo'))
        self.assertFalse(public_judicial_url('https://www.tjsp.jus.br.evil.test/x'))
        self.assertFalse(public_judicial_url('https://user:secret@www.tjsp.jus.br/x'))
        self.assertFalse(public_judicial_url('http://www.tjsp.jus.br/x'))

class PangeaImportScopeTests(TestCase):
    @patch('src.db.management.commands.sync_pangea.PangeaPublicSearchClient')
    def test_aliases_provenance_and_reimport_are_idempotent(self, mock):
        client = mock.return_value
        client.get_catalog.return_value = CATALOG
        client.search_page.return_value = {'total': 3, 'resultados':
            [row('TJSP','sao-paulo'), row('TJDF','distrito'), row('TRF01','federal')]}
        for _ in range(2):
            call_command('sync_pangea', stdout=io.StringIO())
        self.assertEqual(LegalReference.objects.count(), 3)
        reference = LegalReference.objects.get(identifier='distrito')
        self.assertEqual(reference.source_institution, 'TJDFT')
        self.assertEqual(reference.source_metadata['source_orgao'], 'TJDF')
        self.assertIsNone(reference.published_at)
        self.assertFalse(reference.approved)
        self.assertIn('orgao=tjdf', reference.source_url)
        self.assertIn('url', reference.related_decisions[0])
        report = report_references({'court':'TJSP','subject':None,
                                   'start':'2016-01-01','end':'2026-12-31'})
        self.assertEqual(report['inventory_count'], 1)
        self.assertTrue(report['items'][0]['title'].startswith('TJSP'))

    @patch('src.db.management.commands.sync_pangea.PangeaPublicSearchClient')
    def test_start_page_and_next_page_are_explicit(self, mock):
        client = mock.return_value
        client.get_catalog.return_value = CATALOG
        client.search_page.return_value = {'total':100, 'resultados':[row('TJSP')]}
        call_command('sync_pangea', courts='TJSP', start_page=2, page_size=1,
                     max_pages=1, stdout=io.StringIO())
        run = PangeaImportRun.objects.latest('pk')
        self.assertEqual(run.scope['organs'], ['TJSP'])
        self.assertEqual(run.scope['next_page'], 3)
        self.assertEqual(run.status, 'partial')
        client.search_page.assert_called_once_with('responsabilidade civil', 2, 1, courts=('TJSP',))

    @patch('src.db.management.commands.sync_pangea.PangeaPublicSearchClient')
    def test_failed_page_does_not_advance_cursor(self, mock):
        client = mock.return_value
        client.get_catalog.return_value = CATALOG
        client.search_page.side_effect = PangeaError('transient source failure')
        with self.assertRaises(CommandError):
            call_command('sync_pangea', start_page=4, stdout=io.StringIO())
        run = PangeaImportRun.objects.latest('pk')
        self.assertEqual(run.scope['next_page'], 4)
        self.assertEqual(run.pages, 0)
        self.assertEqual(run.status, 'failed')
