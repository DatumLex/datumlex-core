import hashlib
import io
import json
import tempfile
from pathlib import Path
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase,override_settings
from src.db.models import LegalReference,PangeaImportRun

class PangeaRawImportTests(TestCase):
    def archive(self,root,payload):
        raw=json.dumps(payload).encode();sha=hashlib.sha256(raw).hexdigest();(root/'pages'/f'{sha}.json').write_bytes(raw)
        return {'page':0,'path':f'pages/{sha}.json','sha256':sha,'source_complete':True,'query':'responsabilidade civil','courts':['TJSP']}
    def manifest(self,root,page):
        raw=json.dumps({'orgaos':[{'sigla':'TJSP'}],'especies':[{'sigla':'SUM'}]}).encode();(root/'catalog.json').write_bytes(raw)
        manifest={'query':'responsabilidade civil','courts':['TJSP'],'catalog_version':'test','catalog_path':'catalog.json',
            'catalog_sha256':hashlib.sha256(raw).hexdigest(),'pages':[page],'status':'completed'}
        (root/'manifest.json').write_text(json.dumps(manifest),encoding='utf8')
        return manifest
    def test_offline_import_repeats_safely_and_preserves_reviewed_enrichment(self):
        with tempfile.TemporaryDirectory() as temporary,override_settings(BASE_DIR=Path(temporary)):
            root=Path(temporary)/'data/operations/pangea-raw';(root/'pages').mkdir(parents=True)
            payload={'resultados':[{'id':'tjsp-sum-1','orgao':'TJSP','tipo':'SUM','nr':1,'tese':'Dano moral'}],'total':1}
            page=self.archive(root,payload);manifest=self.manifest(root,page)
            call_command('import_pangea_raw',stdout=io.StringIO())
            call_command('import_pangea_raw',stdout=io.StringIO())
            self.assertEqual(LegalReference.objects.count(),1);self.assertEqual(PangeaImportRun.objects.count(),1)
            reference=LegalReference.objects.get();reference.approved=True;reference.title='Titulo revisado';reference.thesis='Tese revisada';reference.save()
            page=self.archive(root,{**payload,'total':2});manifest['pages']=[page]
            (root/'manifest.json').write_text(json.dumps(manifest),encoding='utf8')
            call_command('import_pangea_raw',stdout=io.StringIO())
            reference.refresh_from_db();self.assertTrue(reference.approved)
            self.assertEqual(reference.title,'Titulo revisado');self.assertEqual(reference.thesis,'Tese revisada')
    def test_changed_artifact_is_rejected_before_loading_reference(self):
        with tempfile.TemporaryDirectory() as temporary,override_settings(BASE_DIR=Path(temporary)):
            root=Path(temporary)/'data/operations/pangea-raw';(root/'pages').mkdir(parents=True)
            page=self.archive(root,{'resultados':[],'total':0});self.manifest(root,page)
            (root/page['path']).write_bytes(b'changed')
            with self.assertRaises(CommandError):call_command('import_pangea_raw',stdout=io.StringIO())
            self.assertEqual(LegalReference.objects.count(),0)
            self.assertEqual(PangeaImportRun.objects.get().status,'failed')
