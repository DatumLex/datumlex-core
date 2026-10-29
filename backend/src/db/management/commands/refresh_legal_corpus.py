"""Rebuild a local discovery index from stored texts and references; no network."""
import hashlib
import json
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import OuterRef, Subquery
from src.db.court_catalog import ACTIVE_COURTS
from src.db.models import NlpTextVersion, LegalReference, LegalCorpusItem, LegalCorpusTopicMatch
from src.services.corpus_catalog import VERSION, classify, fingerprint, parse_date, safe_url


def persist(rows):
    if not rows:return
    with transaction.atomic():
        LegalCorpusItem.objects.bulk_create([item for item,_ in rows], update_conflicts=True,
            unique_fields=['origin_key'], update_fields=['category','court','title','source_name','source_url',
            'content_kind','date','date_kind','excerpt','authors','review_status','fingerprint','provenance','indexed_at'])
        ids=dict(LegalCorpusItem.objects.filter(origin_key__in=[item.origin_key for item,_ in rows]).values_list('origin_key','id'))
        LegalCorpusTopicMatch.objects.filter(item_id__in=ids.values()).delete()
        LegalCorpusTopicMatch.objects.bulk_create([
            LegalCorpusTopicMatch(item_id=ids[item.origin_key],topic=topic,matched_terms=terms)
            for item,matches in rows for topic,terms in matches.items()])


def doctrine_text(metadata):
    root=(Path(settings.BASE_DIR)/'data/operations/doctrine').resolve()
    raw_path=metadata.get('text_path')
    if not isinstance(raw_path,str):return '', 'bibliography_only'
    path=(root/raw_path).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size>2_000_000:
        return '', 'bibliography_only'
    text=path.read_text(encoding='utf8')
    if hashlib.sha256(text.encode('utf8')).hexdigest()!=metadata.get('text_sha256'):
        return '', 'bibliography_only'
    return text, 'verified_local_text'


class Command(BaseCommand):
    help='Atualiza indice tematico com documentos locais; nao coleta fontes externas.'
    def add_arguments(self,parser):
        parser.add_argument('--category', choices=['all','jurisprudence','precedent','doctrine'], default='all')
    def handle(self,*args,**options):
        config=settings.DATABASES['default']
        if config['ENGINE']!='django.db.backends.sqlite3' and config.get('HOST') not in ('localhost','127.0.0.1','::1'):
            raise CommandError('O indice deve ser atualizado no banco local.')
        category=options['category']
        known=dict(LegalCorpusItem.objects.values_list('origin_key','fingerprint'))
        batch=[]; changed=unchanged=0
        if category in ('all','jurisprudence'):
            latest=NlpTextVersion.objects.filter(document_id=OuterRef('document_id')).order_by('-created_at','-pk').values('pk')[:1]
            versions=NlpTextVersion.objects.filter(pk=Subquery(latest),document__court__in=ACTIVE_COURTS).select_related('document')
            for version in versions.iterator(chunk_size=100):
                source=version.source
                key='nlp:'+version.document.source_key
                digest=fingerprint({'version':VERSION,'sha256':version.sha256,'source':source})
                if known.get(key)==digest:
                    unchanged+=1;continue
                matches=classify(version.text)
                decision=source.get('decision_date'); publication=source.get('publication_date')
                day=parse_date(decision or publication)
                item=LegalCorpusItem(origin_key=key,category='jurisprudence',court=version.document.court,
                    title=(str(source.get('process_number') or version.document.source_key))[:500],
                    source_name=source.get('source_name') or version.document.court,
                    source_url=safe_url(source.get('source_url')),
                    content_kind=source.get('content_kind','full_text'),date=day,
                    date_kind=('decision_date' if decision else 'publication_date') if day else '',
                    excerpt=version.text[:600],fingerprint=digest,
                    provenance={'text_version':str(version.pk),'sha256':version.sha256,'classifier':VERSION})
                batch.append((item,matches));changed+=1
                if len(batch)>=200:persist(batch);batch=[]
        if category in ('all','precedent','doctrine'):
            refs=LegalReference.objects.all()
            if category!='all':refs=refs.filter(reference_type=category)
            for reference in refs.iterator(chunk_size=200):
                kind=reference.reference_type
                if kind=='precedent' and reference.source_institution not in ACTIVE_COURTS:continue
                if kind not in ('precedent','doctrine'):continue
                metadata=reference.source_metadata if isinstance(reference.source_metadata,dict) else {}
                key='reference:'+str(reference.pk)
                digest=fingerprint({'version':VERSION,'payload':reference.source_payload_hash,
                    'title':reference.title,'thesis':reference.thesis,'metadata':metadata,
                    'published_at':reference.published_at,'approved':reference.approved})
                if known.get(key)==digest:
                    unchanged+=1;continue
                body=reference.thesis;basis='source_reference_text'
                if kind=='doctrine':
                    text,basis=doctrine_text(metadata)
                    body+=' '+text
                matches=classify(reference.title+' '+body)
                authors=metadata.get('authors',[])
                if not isinstance(authors,list):authors=[]
                item=LegalCorpusItem(origin_key=key,category=kind,
                    court=reference.source_institution if kind=='precedent' else '',
                    title=reference.title,source_name=reference.source_name,
                    source_url=safe_url(reference.source_url),
                    content_kind=metadata.get('content_kind') or ('doctrine_article' if kind=='doctrine' else 'precedent_reference'),
                    date=reference.published_at,date_kind='publication_date' if reference.published_at else '',
                    excerpt=body.strip()[:600],authors=authors,
                    review_status='approved' if reference.approved else 'pending',fingerprint=digest,
                    provenance={'reference_id':reference.pk,'classifier':VERSION,'classification_basis':basis})
                batch.append((item,matches));changed+=1
                if len(batch)>=200:persist(batch);batch=[]
        persist(batch)
        self.stdout.write(json.dumps({'indexed_or_updated':changed,'unchanged':unchanged,
            'classification':'lexical_candidates_pending_review','network_requests':0}))
