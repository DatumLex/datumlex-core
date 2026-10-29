import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src.nlp.cache import ComputationCache
from src.nlp.contracts import bytes_hash
from src.nlp.extraction import extract
from src.nlp.journal import Journal
from src.nlp.pipeline import process

class ComputationCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.cache=ComputationCache(self.root/'cache');self.addCleanup(self.cache.close)
        self.journal=Journal(self.root/'run.sqlite3');self.addCleanup(self.journal.close)
        self.manifest={'schema_version':'0.1.0','input_manifest_sha256':'a','parameters':{'short_threshold':200,'max_paragraph':6000},'code_hashes':{'extraction':'v1'}}
    def source(self,text='A responsabilidade civil depende do nexo causal.'):
        raw=text.encode();(self.root/'source.txt').write_bytes(raw)
        return {'document_id':'STJ:test','court':'STJ','source_version':bytes_hash(raw),'artifact_path':'source.txt',
                'artifact_sha256':bytes_hash(raw),'text_sha256':bytes_hash(raw)}
    @patch('src.nlp.pipeline.extract',wraps=extract)
    def test_growing_global_queue_reuses_only_computation(self,run_extract):
        row=self.source()
        first,cached=process(row,self.root,self.manifest,self.journal,computation_cache=self.cache)
        second,cached=process(row,self.root,{**self.manifest,'input_manifest_sha256':'b'},self.journal,computation_cache=self.cache)
        self.assertTrue(cached);self.assertEqual(run_extract.call_count,1)
        self.assertEqual(first['annotations'],second['annotations'])
        self.assertEqual(first['pipeline']['input_manifest_sha256'],'a')
        self.assertEqual(second['pipeline']['input_manifest_sha256'],'b')
        self.assertNotEqual(first['result_sha256'],second['result_sha256'])
        self.assertEqual(second['review']['status'],'pending')
    @patch('src.nlp.pipeline.extract',wraps=extract)
    def test_source_or_rules_change_invalidates_cache(self,run_extract):
        row=self.source();process(row,self.root,self.manifest,self.journal,computation_cache=self.cache)
        row=self.source('A responsabilidade civil independe de culpa.')
        process(row,self.root,self.manifest,self.journal,computation_cache=self.cache)
        process(row,self.root,{**self.manifest,'code_hashes':{'extraction':'v2'}},self.journal,computation_cache=self.cache)
        self.assertEqual(run_extract.call_count,3)
    def test_deleted_original_is_rejected_despite_cached_result(self):
        row=self.source();process(row,self.root,self.manifest,self.journal,computation_cache=self.cache)
        (self.root/'source.txt').unlink()
        result,cached=process(row,self.root,{**self.manifest,'input_manifest_sha256':'b'},self.journal,computation_cache=self.cache)
        self.assertFalse(cached);self.assertNotIn(result['status'],('completed','partial'))
    def test_corrupt_cache_never_creates_successful_predictions(self):
        row=self.source();result,_=process(row,self.root,self.manifest,self.journal,computation_cache=self.cache)
        db=self.cache.connection(result['computation_key'])
        with db:db.execute("UPDATE results SET payload='{}'")
        result,cached=process(row,self.root,{**self.manifest,'input_manifest_sha256':'b'},self.journal,computation_cache=self.cache)
        self.assertEqual(result['status'],'failed');self.assertFalse(cached)
