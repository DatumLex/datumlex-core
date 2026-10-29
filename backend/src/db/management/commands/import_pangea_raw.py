"""Import verified archived Pangea pages offline, in per-page transactions."""
import hashlib
import io
import json
from pathlib import Path
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from django.utils import timezone
from src.api.pangea_scope import selected_courts
from src.db.models import PangeaImportRun
from src.db.management.commands.sync_pangea import _normalize, store_reference


def read_artifact(root,relative,sha):
    path=(root/relative).resolve()
    if not path.is_relative_to(root.resolve()):raise ValueError('Artifact outside archived source')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('Archived Pangea hash mismatch')
    return json.loads(raw)

class Command(BaseCommand):
    help='Importa respostas Pangea arquivadas sem rede; preserva aprovacao humana.'
    def handle(self,*args,**options):
        config=settings.DATABASES['default']
        if config['ENGINE']!='django.db.backends.sqlite3' and config.get('HOST') not in ('localhost','127.0.0.1','::1'):
            raise CommandError('Local database required')
        root=Path(settings.BASE_DIR)/'data/operations/pangea-raw'
        manifest=json.loads((root/'manifest.json').read_bytes())
        if (root/'all-pages.json').exists():
            pages=json.loads((root/'all-pages.json').read_bytes())['pages']
            if pages:
                manifest.update({'pages':pages,'status':'completed' if pages[-1]['source_complete'] else 'partial'})
        normalizer_sha=hashlib.sha256(Path(__file__).read_bytes()+Path(__file__).with_name('sync_pangea.py').read_bytes()).hexdigest()
        consumed=set()
        for scope in PangeaImportRun.objects.filter(scope__archive_consumed=True,scope__normalizer_sha=normalizer_sha).values_list('scope',flat=True):
            consumed.update(scope.get('raw_pages',[]))
        manifest['pages']=[page for page in manifest['pages'] if page.get('receipt_key',page['sha256']) not in consumed]
        if not manifest['pages']:
            self.stdout.write('No unconsumed archived Pangea pages.');return
        stable={k:v for k,v in manifest.items() if k not in ('started_at','finished_at')}
        signature=hashlib.sha256(json.dumps(stable,sort_keys=True).encode()+Path(__file__).read_bytes()+Path(__file__).with_name('sync_pangea.py').read_bytes()).hexdigest()
        if PangeaImportRun.objects.filter(scope__raw_signature=signature,scope__archive_consumed=True).exists():
            self.stdout.write('Pangea archive already imported.');return
        courts=selected_courts(manifest['courts']);read_artifact(root,manifest['catalog_path'],manifest['catalog_sha256'])
        run=PangeaImportRun.objects.create(scope={'query':manifest['query'],'organs':list(courts),'origin':'archived_pangea',
            'raw_signature':signature,'normalizer_sha':normalizer_sha,'raw_pages':[page.get('receipt_key',page['sha256']) for page in manifest['pages']],
            'counting_unit':'archived_response_rows_may_repeat','next_page':manifest['pages'][0]['page'] if manifest['pages'] else 0},catalog_version=manifest.get('catalog_version','')[:64])
        try:
            for page in manifest['pages']:
                if page.get('catalog_path'):read_artifact(root,page['catalog_path'],page['catalog_sha256'])
                payload=read_artifact(root,page['path'],page['sha256'])
                page_courts=selected_courts(page.get('courts',manifest['courts']))
                page_query=page.get('query',manifest['query'])
                with transaction.atomic():
                    for row in payload['resultados']:
                        try:defaults=_normalize(row,run,page_query,page_courts)
                        except ValueError:
                            run.rejected+=1;continue
                        created,updated=store_reference(defaults,page_query);run.created+=created;run.updated+=updated
                    run.pages+=1;run.fetched+=len(payload['resultados']);run.source_total=None;run.scope['last_response_total']=payload['total']
                    run.scope['next_page']=page['page']+1;run.save()
            run.status=PangeaImportRun.COMPLETED if manifest['status']=='completed' and not run.rejected else PangeaImportRun.PARTIAL
            run.scope['archive_consumed']=True
            run.finished_at=timezone.now();run.save()
        except (OSError,ValueError,KeyError,TypeError) as exc:
            run.refresh_from_db();run.status=PangeaImportRun.PARTIAL if run.pages else PangeaImportRun.FAILED
            run.error=type(exc).__name__;run.finished_at=timezone.now();run.save()
            raise CommandError('Archived Pangea import failed: '+type(exc).__name__) from exc
        call_command('refresh_legal_corpus',category='precedent',stdout=io.StringIO())
        self.stdout.write(json.dumps({'run':run.pk,'status':run.status,'new':run.created,'updated':run.updated,'network_requests':0}))
