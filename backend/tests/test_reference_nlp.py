"""Synthetic integration checks for reference text lineage and NLP categories."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.contrib.auth import get_user_model
from src.nlp.contracts import windows_path

from django.test import TestCase, override_settings

from src.db.court_catalog import ACTIVE_COURTS
from src.db.models import LegalCorpusItem, LegalReference, NlpDocument, NlpExtraction
from src.nlp.adapters import SourceProblem, read_source
from src.nlp.contracts import bytes_hash
from src.nlp.reference_sources import reference_queue
from src.nlp.topics import TOPICS
from src.services.nlp_evidence import authorize

PROJECT = Path(__file__).resolve().parents[2]


def load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReferenceNlpTests(TestCase):
    def test_bibliography_only_reference_cycle_completes_without_fabricated_text(self):
        runner = load_script('empty_reference_runner', PROJECT / 'tools/nlp_validation/run_nlp_local.py')
        importer = load_script('empty_reference_importer', PROJECT / 'tools/nlp_validation/import_local_results.py')
        with tempfile.TemporaryDirectory(dir=windows_path(tempfile.gettempdir())) as temporary:
            root = Path(temporary)
            path = root / 'doctrine'
            path.mkdir()
            (path / 'manifest.json').write_text(json.dumps({'documents': {
                'bibliography': {'identifier': 'bibliography'},
            }}))
            job = str(uuid4())
            with patch.object(runner, 'ROOT', root), patch.object(sys, 'argv', [
                    'run_nlp_local', '--job-id', job, '--sources', 'doctrine']), \
                    patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(runner.main(), 0)
            with patch.object(importer, 'ROOT', root), patch.object(sys, 'argv', [
                    'import_local_results', '--job-id', job]), patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(importer.main(), 0)
            self.assertFalse(NlpDocument.objects.exists())

    def sources(self, root):
        pangea = root / 'pangea-raw'
        pangea.mkdir()
        records = [{'id': 'ref-' + court, 'orgao': court, 'tipo': 'SUM', 'nr': index,
                    'tese': 'O ' + TOPICS[index][2][0] + ' depende de prova.'}
                   for index, court in enumerate(ACTIVE_COURTS)]
        raw = json.dumps({'resultados': records, 'total': len(records)}).encode()
        (pangea / 'page.json').write_bytes(raw)
        (pangea / 'all-pages.json').write_text(json.dumps({'pages': [
            {'path': 'page.json', 'sha256': bytes_hash(raw)},
        ]}))
        doctrine = root / 'doctrine'
        doctrine.mkdir()
        text = 'A responsabilidade civil depende do nexo causal, pois o dano exige prova.'
        (doctrine / 'article.txt').write_bytes(text.encode())
        (doctrine / 'article.pdf').write_bytes(b'Synthetic PDF original')
        entry = {'identifier': 'article', 'text_path': 'article.txt',
                 'text_sha256': bytes_hash(text.encode()), 'pdf_path': 'article.pdf',
                 'pdf_sha256': bytes_hash(b'Synthetic PDF original'),
                 'source_url': 'https://www12.senado.leg.br/synthetic',
                 'source_institution': 'Senado', 'published_at': '2020-01-01'}
        (doctrine / 'manifest.json').write_text(json.dumps({'documents': {'article': entry}}))

    def test_cli_import_keeps_all_courts_topics_and_reference_categories(self):
        runner = load_script('reference_runner', PROJECT / 'tools/nlp_validation/run_nlp_local.py')
        importer = load_script('reference_importer', PROJECT / 'tools/nlp_validation/import_local_results.py')
        with tempfile.TemporaryDirectory(dir=windows_path(tempfile.gettempdir())) as temporary:
            root = Path(temporary) / 'data/operations'
            root.mkdir(parents=True)
            self.sources(root)
            rows, _ = reference_queue(root, {'pangea', 'doctrine'})
            for row in rows:
                LegalReference.objects.create(
                    reference_type=row['category'], source_institution=row['court'] or 'Senado',
                    identifier=row['record_id'] if row['category'] == 'precedent' else 'article',
                    title=row['document_id'], thesis='A responsabilidade civil depende de prova.',
                    source_name=row['source_name'], source_url=row['source_url'],
                    source_payload_hash=row['reference_payload_hash'],
                )
            job = str(uuid4())
            with patch.object(runner, 'ROOT', root), patch.object(sys, 'argv', [
                    'run_nlp_local', '--job-id', job, '--sources', 'pangea,doctrine']), \
                    patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(runner.main(), 0)
            coverage = json.loads((root / 'nlp-local/jobs' / job / 'coverage.json').read_bytes())
            self.assertEqual(coverage['texts_by_year']['2020'], 1)
            self.assertEqual(coverage['texts_by_publisher'], {'Senado': 1})
            self.assertNotIn('', coverage['texts_by_court'])
            with override_settings(BASE_DIR=Path(temporary)), patch.object(importer, 'ROOT', root), \
                    patch.object(sys, 'argv', ['import_local_results', '--job-id', job]), \
                    patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(importer.main(), 0)
                self.assertEqual(importer.main(), 0)
                call_command('refresh_legal_corpus', stdout=io.StringIO())
            self.assertEqual(NlpDocument.objects.count(), 11)
            self.assertEqual(NlpExtraction.objects.count(), 11)
            self.assertEqual(set(NlpDocument.objects.exclude(court='').values_list('court', flat=True)),
                             set(ACTIVE_COURTS))
            doctrine = NlpExtraction.objects.get(document__source_key='DOCTRINE:article')
            self.assertEqual(doctrine.document.court, '')
            self.assertEqual(doctrine.original_result['coverage']['category'], 'doctrine')
            reader = get_user_model().objects.create_user(
                username='doctrine_reader', approved=True, must_change_password=False,
            )
            authorize(reader, doctrine.document)
            with self.assertRaises(PermissionError):
                authorize(reader, doctrine.document, write=True)
            precedent = NlpDocument.objects.get(source_key='PANGEA:STJ:ref-STJ')
            with self.assertRaises(PermissionError):
                authorize(reader, precedent)
            topics = set()
            for result in NlpExtraction.objects.values_list('original_result', flat=True):
                topics.update(result['topics']['matches'])
            self.assertEqual(topics, {key for key, _, _ in TOPICS})
            self.assertFalse(LegalCorpusItem.objects.filter(category='jurisprudence').exists())
            self.assertEqual(LegalCorpusItem.objects.count(), 11)
            self.assertEqual(LegalCorpusItem.objects.filter(provenance__nlp_status='completed').count(), 11)

    def test_reference_reader_rejects_changed_sources_and_bibliography_only(self):
        with tempfile.TemporaryDirectory(dir=windows_path(tempfile.gettempdir())) as temporary:
            root = Path(temporary)
            self.sources(root)
            rows, excluded = reference_queue(root, {'pangea', 'doctrine'})
            self.assertEqual(len(rows), 11)
            self.assertEqual(excluded, {})
            doctrine = next(row for row in rows if row['category'] == 'doctrine')
            (root / 'doctrine/article.pdf').write_bytes(b'Changed original')
            with self.assertRaises(SourceProblem):
                read_source(doctrine, root)
            manifest = root / 'doctrine/manifest.json'
            value = json.loads(manifest.read_bytes())
            del value['documents']['article']['text_path']
            manifest.write_text(json.dumps(value))
            rows, excluded = reference_queue(root, {'doctrine'})
            self.assertEqual(rows, [])
            self.assertEqual(excluded, {'doctrine_without_verified_text': 1})
