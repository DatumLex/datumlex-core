"""End-to-end synthetic job: archived source -> CLI -> isolated import."""
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch
from django.test import TestCase
from src.db.models import NlpDocument,NlpExtraction

PROJECT=Path(__file__).resolve().parents[2]

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

class JobIsolationTests(TestCase):
    def test_isolated_queue_and_result_pointer_are_used_by_importer(self):
        run=load('isolated_nlp_runner',PROJECT/'tools/nlp_validation/run_nlp_local.py')
        importer=load('isolated_nlp_importer',PROJECT/'tools/nlp_validation/import_local_results.py')
        with tempfile.TemporaryDirectory(prefix='datumlex-job-test-') as temporary:
            root=Path(temporary);texts=root/'stj-documents/texts';texts.mkdir(parents=True)
            raw=('Documento sintetico. O dano moral depende de prova. '+('Contexto de teste. '*20)).encode()
            (texts/'1-synthetic.txt').write_bytes(raw)
            (root/'stj-documents/metadata-test.json').write_text(json.dumps([{'SeqDocumento':'1','dataPublicacao':'2016-01-01'}]),encoding='utf8')
            job=str(uuid.uuid4())
            with patch.object(run,'ROOT',root),patch.object(sys,'argv',['run_nlp_local','--job-id',job]),patch('sys.stdout',new_callable=io.StringIO):
                self.assertEqual(run.main(),0)
            output=root/'nlp-local/jobs'/job
            self.assertTrue((output/'queue.json').exists())
            pointer=json.loads((output/'current-run.json').read_text())
            self.assertTrue(Path(pointer['directory']).is_relative_to(output/'runs'))
            # A corrupt legacy pointer must not affect this job's import.
            (root/'nlp-local/current-run.json').write_text('{"directory":"wrong"}')
            with patch.object(importer,'ROOT',root),patch.object(sys,'argv',['import_local_results','--job-id',job]),patch('sys.stdout',new_callable=io.StringIO):
                self.assertEqual(importer.main(),0)
            self.assertEqual(NlpDocument.objects.count(),1)
            self.assertEqual(NlpExtraction.objects.count(),1)
