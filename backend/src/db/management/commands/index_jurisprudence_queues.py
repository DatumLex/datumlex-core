"""Expose verified newly collected texts in discovery while NLP is pending."""
import json
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from src.db.models import LegalCorpusItem, LegalCorpusTopicMatch
from src.db.court_catalog import ACTIVE_COURTS
from src.nlp.adapters import read_source
from src.services.corpus_catalog import classify, fingerprint, parse_date, safe_url, VERSION
from src.services.period import HISTORY_START, today

class Command(BaseCommand):
    help='Indexa textos coletados e verificados para descoberta; nao executa nem aprova NLP.'
    def handle(self,*args,**options):
        config=settings.DATABASES['default']
        if config['ENGINE']!='django.db.backends.sqlite3' and config.get('HOST') not in ('localhost','127.0.0.1','::1'):
            raise CommandError('Local database required')
        root=Path(settings.BASE_DIR)/'data/operations'
        known=set(LegalCorpusItem.objects.filter(category='jurisprudence').values_list('origin_key',flat=True))
        created=rejected=0
        for relative in ('tjdft-documents/documents.json','jurisprudence-ementas/queue.json','djen-documents/queue.json'):
            path=root/relative
            if not path.exists():continue
            rows=json.loads(path.read_text(encoding='utf8'))
            if isinstance(rows,dict):rows=rows.values()
            for row in rows:
                if row.get('court') not in ACTIVE_COURTS:continue
                key='nlp:'+row['document_id']
                if key in known:continue
                day=parse_date(row.get('decision_date') or row.get('publication_date'))
                if not day or not HISTORY_START<=day<=today():
                    rejected+=1;continue
                if row.get('content_kind','full_text') not in ('full_text','ementa','publication_excerpt'):
                    rejected+=1;continue
                try:text=read_source(row,root)
                except (OSError,ValueError,KeyError,TypeError):
                    rejected+=1;continue
                matches=classify(text)
                with transaction.atomic():
                    item,inserted=LegalCorpusItem.objects.get_or_create(origin_key=key,defaults={
                        'category':'jurisprudence','court':row['court'],
                        'title':str(row.get('process_number') or row['document_id'])[:500],
                        'source_name':row['court'],'source_url':safe_url(row.get('source_url')),
                        'content_kind':row.get('content_kind','full_text'),'date':day,
                        'date_kind':'decision_date' if row.get('decision_date') else 'publication_date',
                        'excerpt':text[:600],'fingerprint':fingerprint({'row':row,'classifier':VERSION,'pending_nlp':True}),
                        'provenance':{'sha256':row['text_sha256'],'artifact_sha256':row['artifact_sha256'],
                                      'pending_nlp':True,'classifier':VERSION}})
                    if inserted:
                        LegalCorpusTopicMatch.objects.bulk_create([LegalCorpusTopicMatch(item=item,topic=topic,matched_terms=terms)
                                                                  for topic,terms in matches.items()])
                        created+=1
                known.add(key)
        self.stdout.write(json.dumps({'new_discovery_items':created,'rejected':rejected,'nlp_state':'pending','nlp_documents_created':0}))
