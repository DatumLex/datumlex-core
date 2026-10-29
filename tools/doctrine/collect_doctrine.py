"""Acquire publicly available doctrine PDFs and page-linked text, never legal approval."""
import argparse
from datetime import datetime
import hashlib
from html.parser import HTMLParser
import io
import json
import os
import re
from pathlib import Path
import sys
import time
from urllib.parse import urlparse
from urllib.request import urlopen

from pypdf import PdfReader

PROJECT = Path(__file__).resolve().parents[2]
ROOT = PROJECT / 'backend/data/operations/doctrine'
sys.path.insert(0, str(PROJECT / 'backend'))
sys.path.insert(0, str(PROJECT / 'tools/nlp_validation'))
from src.services.period import today
from datetime import date

# Exact publisher landing pages; titles, authors and dates are read from citation metadata.
RIL_PAGES = [
    'https://www12.senado.leg.br/ril/edicoes/61/241/ril_v61_n241_p237',
    'https://www12.senado.leg.br/ril/edicoes/56/222/ril_v56_n222_p33',
    'https://www12.senado.leg.br/ril/edicoes/57/226/ril_v57_n226_p71',
    'https://www12.senado.leg.br/ril/edicoes/60/237/ril_v60_n237_p141',
    'https://www12.senado.leg.br/ril/edicoes/61/241/ril_v61_n241_p117',
]
STJ_DOCTRINE = 'https://www.stj.jus.br/docs_internet/revista/eletronica/stj-revista-eletronica-2016_241_capDoutrina.pdf'
ALLOWED_HOSTS = ('www12.senado.leg.br', 'www.stj.jus.br', 'ww2.stj.jus.br', 'bdjur.stj.jus.br')


class CitationMetadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        name = attrs.get('name', '')
        if tag == 'meta' and name.startswith('citation_') and attrs.get('content'):
            self.values.setdefault(name, []).append(attrs['content'].strip())


def fetch(url, maximum=20_000_000):
    if urlparse(url).scheme != 'https' or urlparse(url).hostname not in ALLOWED_HOSTS:
        raise ValueError('Unapproved publisher URL')
    with urlopen(url, timeout=40) as response:
        if urlparse(response.url).hostname not in ALLOWED_HOSTS:
            raise ValueError('Unexpected source redirect')
        raw = response.read(maximum + 1)
        charset = response.headers.get_content_charset() or 'utf8'
    if len(raw) > maximum:
        raise ValueError('Source exceeds download bound')
    return raw, charset


def parse_date(value):
    for fmt in ('%Y/%m/%d', '%Y-%m-%d'):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def page_text(raw):
    if not raw.startswith(b'%PDF-'):
        raise ValueError('Publisher did not return a PDF')
    reader = PdfReader(io.BytesIO(raw))
    if reader.is_encrypted:
        raise ValueError('Encrypted document is not processed')
    pages = [{'page': number + 1, 'text': page.extract_text() or ''} for number, page in enumerate(reader.pages)]
    text = '\n\n'.join(f'[Página {row["page"]}]\n{row["text"]}' for row in pages)
    if len(re.findall(r'/u[0-9a-fA-F]{4,6}', text)) >= 50:
        raise ValueError('Unreliable font mapping; alternate extraction or manual review required')
    if len(''.join(row['text'] for row in pages).strip()) < 500:
        raise ValueError('No sufficient extractable text; OCR or manual review required')
    return pages, text


def collect(import_db=False,sources=None,extract_text=True):
    sys.path.insert(0,str(PROJECT/'tools/nlp_validation'))
    from etl_runtime import file_lock
    with file_lock(ROOT/'source.lock'):
        return _collect(import_db,sources,extract_text)

def _collect(import_db=False, sources=None,extract_text=True):
    from etl_runtime import archive_bytes, atomic_json
    ROOT.mkdir(parents=True, exist_ok=True)
    for folder in ('metadata', 'pdf', 'text'):
        (ROOT / folder).mkdir(exist_ok=True)
    manifest_path = ROOT / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf8')) if manifest_path.exists() else {'documents': {}, 'attempts': []}
    before = len(manifest['documents'])
    pending_before=len(manifest.get('pending',{}))
    failed = 0
    sources = sources if sources is not None else [('Senado', url) for url in RIL_PAGES] + [('STJ', STJ_DOCTRINE)]
    for institution, url in sources:
        try:
            if institution == 'Senado':
                raw_metadata, charset = fetch(url, 2_000_000)
                parser = CitationMetadata()
                parser.feed(raw_metadata.decode(charset, errors='strict'))
                metadata = parser.values
                title = metadata['citation_title'][0]
                authors = metadata.get('citation_author', [])
                pdf_url = metadata['citation_pdf_url'][0].replace('http://', 'https://', 1)
                publication = parse_date(metadata.get('citation_publication_date', [''])[0])
                year = publication.year if publication else None
                if not publication or not date(2016, 1, 1) <= publication <= today():
                    raise ValueError('Outside requested publication period')
                content_kind = 'doctrine_article'
            else:
                title = 'Revista do Superior Tribunal de Justiça — Doutrina — volume 241 (2016)'
                authors, metadata, raw_metadata, pdf_url = [], {}, None, url
                publication, year, content_kind = None, 2016, 'doctrine_collection'
            raw, _ = fetch(pdf_url)
            sha=hashlib.sha256(raw).hexdigest();key=hashlib.sha256(url.encode()).hexdigest()
            pdf_path=ROOT/'pdf'/f'{key}-{sha}.pdf'
            archive_bytes(pdf_path,raw)
            metadata_sha=None
            if raw_metadata:
                metadata_sha=hashlib.sha256(raw_metadata).hexdigest()
                archive_bytes(ROOT/'metadata'/f'{key}-{metadata_sha}.html',raw_metadata)
            entry={'identifier':key,'title':title,'authors':authors,'source_institution':institution,
                'source_url':url,'pdf_url':pdf_url,'published_at':publication.isoformat() if publication else None,
                'publication_year':year,'date_precision':'day' if publication else 'year','content_kind':content_kind,
                'pdf_path':pdf_path.relative_to(ROOT).as_posix(),'pdf_sha256':sha,'metadata':metadata,
                'metadata_sha256':metadata_sha,'access_status':'public_download_succeeded',
                'rights_approval':'pending','bibliographic_review':'pending','legal_review':'pending'}
            if extract_text:
                entry=extract_entry(entry)
                manifest['documents'][key]=entry
            else:
                manifest.setdefault('pending',{})[key]=entry
            print(json.dumps({'institution':institution,'title':title,'pages':entry.get('pages'),
                              'state':'text_extracted' if extract_text else 'original_archived_pending_extraction'},ensure_ascii=False),flush=True)
        except Exception as exc:
            failed += 1
            manifest['attempts'].append({'url': url, 'state': 'unavailable_or_not_extractable',
                'error_type': type(exc).__name__, 'http_status': getattr(exc, 'code', None)})
            print(json.dumps({'url': url, 'state': 'failed', 'error_type': type(exc).__name__,
                              'http_status': getattr(exc, 'code', None)}), flush=True)
        atomic_json(manifest_path,manifest)
        time.sleep(.3)
    if import_db:
        import_manifest(manifest)
    result = {'raw_pending':len(manifest.get('pending',{})), 'new_raw_documents':len(manifest.get('pending',{}))-pending_before, 'new_documents': len(manifest['documents']) - before, 'failed_this_run': failed, 'doctrine_documents': len(manifest['documents']),
              'articles': sum(e['content_kind'] == 'doctrine_article' for e in manifest['documents'].values()),
              'collections': sum(e['content_kind'] == 'doctrine_collection' for e in manifest['documents'].values()),
              'pages': sum(e['pages'] for e in manifest['documents'].values()),
              'legal_review': 'pending', 'database_import_requested': import_db}
    atomic_json(ROOT/'last-run.json',result)
    return result



def extract_entry(entry):
    from etl_runtime import archive_bytes
    path=(ROOT/entry['pdf_path']).resolve()
    if not path.is_relative_to(ROOT.resolve()):raise ValueError('Doctrine artifact outside archive')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=entry['pdf_sha256']:raise ValueError('Doctrine artifact hash mismatch')
    pages,text=page_text(raw);text_sha=hashlib.sha256(text.encode('utf8')).hexdigest()
    basename=f"{entry['identifier'][:16]}-{entry['pdf_sha256'][:16]}-{text_sha}"
    text_path=ROOT/'text'/(basename+'.txt');pages_path=ROOT/'text'/(basename+'.pages.json')
    archive_bytes(text_path,text.encode('utf8'))
    archive_bytes(pages_path,json.dumps(pages,ensure_ascii=False,indent=2).encode('utf8'))
    return {**entry,'pages':len(pages),'characters':len(text),
        'text_path':text_path.relative_to(ROOT).as_posix(),'text_sha256':text_sha,
        'page_text_path':pages_path.relative_to(ROOT).as_posix(),'text_extraction_status':'completed'}


def import_manifest(manifest):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.conf import settings
    from src.db.models import LegalReference
    from django.db import transaction
    config = settings.DATABASES['default']
    if config['ENGINE'] != 'django.db.backends.sqlite3' and config.get('HOST') not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Only a local database may receive the doctrine corpus')
    for entry in manifest['documents'].values():
        for path_key,hash_key,as_text in (('pdf_path','pdf_sha256',False),('text_path','text_sha256',True)):
            path=(ROOT/entry[path_key]).resolve()
            if not path.is_relative_to(ROOT.resolve()):raise ValueError('Doctrine artifact outside local archive')
            raw=path.read_text(encoding='utf8').encode('utf8') if as_text else path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=entry[hash_key]:raise ValueError('Doctrine artifact hash mismatch')
        if entry['source_institution'] not in ('Senado','STJ'):raise ValueError('Unknown doctrine publisher')
        name = 'Revista de Informação Legislativa — Senado Federal' if entry['source_institution'] == 'Senado' else 'Revista do STJ — seção Doutrina'
        with transaction.atomic():
            existing = LegalReference.objects.select_for_update().filter(source_name=name, identifier=entry['identifier']).first()
            # Stable reimports must preserve a human approval; changed bytes require a new review.
            approved = bool(existing and existing.approved and existing.source_payload_hash == entry['pdf_sha256'])
            defaults={
                'reference_type': LegalReference.DOCTRINE, 'source_institution': entry['source_institution'],
                'title': entry['title'][:500], 'thesis': '', 'authority': 'Doutrina — apoio bibliográfico',
                'source_url': entry['source_url'], 'source_locator': 'PDF e texto por página; manifesto local de doutrina',
                'published_at': entry['published_at'], 'source_metadata': entry,
                'source_payload_hash': entry['pdf_sha256'], 'approved': approved,
                'approval_reference': existing.approval_reference if approved else 'Coleta pública; revisão bibliográfica e direitos pendentes'}
            if existing and existing.source_payload_hash==entry['pdf_sha256']:
                for field in ('title','thesis','published_at','subject_code','authority'):
                    defaults[field]=getattr(existing,field)
            LegalReference.objects.update_or_create(source_name=name,identifier=entry['identifier'],defaults=defaults)
    from django.core.management import call_command
    call_command('refresh_legal_corpus', category='doctrine')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--import-local', action='store_true')
    args = parser.parse_args()
    print(json.dumps(collect(args.import_local), ensure_ascii=False, indent=2))
