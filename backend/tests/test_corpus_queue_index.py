import hashlib
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from django.core.management import call_command
from django.http import QueryDict
from src.services.corpus_catalog import inventory
from django.test import TestCase, override_settings
from src.db.models import LegalCorpusItem, LegalCorpusTopicMatch, NlpDocument

class CorpusQueueIndexTests(TestCase):
    @patch('src.db.management.commands.index_jurisprudence_queues.read_source')
    def test_new_queued_text_is_visible_without_claiming_nlp_completed(self,read):
        text='Dano moral e responsabilidade civil.'
        read.return_value=text
        with tempfile.TemporaryDirectory() as temporary, override_settings(BASE_DIR=Path(temporary)):
            folder=Path(temporary)/'data/operations/djen-documents';folder.mkdir(parents=True)
            row={'document_id':'TJSP:DJEN:123','court':'TJSP','content_kind':'publication_excerpt',
                 'publication_date':'2026-01-01','source_url':'https://comunicaapi.pje.jus.br/',
                 'text_sha256':hashlib.sha256(text.encode()).hexdigest(),'artifact_sha256':'a'*64}
            (folder/'queue.json').write_text(json.dumps([row]),encoding='utf8')
            for _ in range(2):call_command('index_jurisprudence_queues',stdout=io.StringIO())
        self.assertEqual(LegalCorpusItem.objects.count(),1)
        self.assertEqual(NlpDocument.objects.count(),0)
        self.assertEqual(LegalCorpusTopicMatch.objects.count(),1)
        item=LegalCorpusItem.objects.get()
        self.assertTrue(item.provenance['pending_nlp'])
        self.assertEqual(item.content_kind,'publication_excerpt')
        self.assertEqual(item.review_status,'pending')
        result=inventory(QueryDict('court=TJSP'))
        self.assertEqual(result['items'][0]['processing_status'],'awaiting_nlp')
