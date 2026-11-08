"""Court expansion and content provenance, using synthetic engineering fixtures."""
import json
from pathlib import Path
import tempfile

from django.http import QueryDict
from django.test import SimpleTestCase

from src.db.court_catalog import COURTS, ENDPOINTS, matches_source
from src.etl.transformer import normalize
from src.nlp.adapters import read_source, SourceProblem
from src.nlp.contracts import bytes_hash
from src.services.outcomes import classify
from src.services.statistics_service import filtered_processes
from tests.test_pipeline import hit, SCOPE


class CourtCoverageTests(SimpleTestCase):
    def test_official_registry_has_91_courts_and_known_aliases(self):
        self.assertEqual(len(COURTS), 91)
        self.assertTrue(ENDPOINTS['TRT24'].endswith('api_publica_trt24/_search'))
        self.assertTrue(ENDPOINTS['TRE-DF'].endswith('api_publica_tre-dft/_search'))
        self.assertTrue(matches_source('TRE-DF', 'TREDFT'))
        self.assertFalse(matches_source('TJSP', 'TJMG'))

    def test_ids_are_namespaced_and_new_courts_do_not_inherit_legal_outcome_rules(self):
        record = hit('same-id')
        record['_source']['tribunal'] = 'TJSP'
        normalized = normalize(record, SCOPE | {'court': 'TJSP'})
        self.assertEqual(normalized['source_id'], 'TJSP:same-id')
        process = type('Process', (), {'court': 'TJSP'})()
        self.assertEqual(classify(process)['outcome'], 'unknown')
        _, scope = filtered_processes(QueryDict('court=TJSP,TST&start=2016-01-01'))
        self.assertEqual(scope['court'], 'TJSP,TST')

    def test_djen_keeps_publication_kind_and_verifies_returned_court(self):
        text = 'Publicação de acórdão para teste técnico. ' * 10
        payload = {'items': [{'id': 1, 'siglaTribunal': 'TJSP', 'tipoDocumento': 'Acórdão',
                    'ativo': True, 'texto': text}]}
        with tempfile.TemporaryDirectory() as directory:
            raw = json.dumps(payload).encode()
            Path(directory, 'source.json').write_bytes(raw)
            row = {'artifact_path': 'source.json', 'artifact_sha256': bytes_hash(raw), 'text_sha256': bytes_hash(text.encode()),
                   'court': 'TJSP', 'record_id': '1', 'source_format': 'djen-public-json-v1',
                   'content_kind': 'publication_excerpt', 'text_field': 'texto'}
            self.assertEqual(read_source(row, directory), text)
            with self.assertRaises(SourceProblem):
                read_source(row | {'court': 'TJMG'}, directory)
            with self.assertRaises(SourceProblem):
                read_source(row | {'content_kind': 'full_text'}, directory)

    def test_tst_ementa_cannot_be_imported_as_a_full_decision(self):
        text = 'Ementa de acórdão sintético.'
        payload = {'registros': [{'registro': {'id': 'tst-1', 'ementa': text,
                    'orgao': {'sigla': 'TST'}, 'tipo': {'codigoTipoJurisprudencia': 'ACORDAO'}}}]}
        with tempfile.TemporaryDirectory() as directory:
            raw = json.dumps(payload).encode()
            Path(directory, 'source.json').write_bytes(raw)
            row = {'artifact_path': 'source.json', 'artifact_sha256': bytes_hash(raw), 'text_sha256': bytes_hash(text.encode()),
                   'court': 'TST', 'record_id': 'tst-1', 'source_format': 'tst-search-json-v1',
                   'content_kind': 'ementa', 'text_field': 'ementa'}
            self.assertEqual(read_source(row, directory), text)
            with self.assertRaises(SourceProblem):
                read_source(row | {'content_kind': 'full_text'}, directory)
