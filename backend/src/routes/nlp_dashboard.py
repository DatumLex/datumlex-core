"""Session-authorized #115 read APIs and immutable export handoff."""
import json
from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError
from django.http import HttpResponse, JsonResponse
from django.template import Context, Engine
from django.views.decorators.http import require_http_methods

from src.services import analytical_context as context
from src.services import nlp_dashboard as service
from src.services.nlp_evidence import Conflict


def endpoint(methods):
    def decorate(fn):
        @require_http_methods(methods)
        @wraps(fn)
        def wrapped(request, **kwargs):
            try:
                result = fn(request, **kwargs)
                return result if isinstance(result, HttpResponse) else JsonResponse(result)
            except Conflict as exc:
                return JsonResponse({'error': {'code': str(exc), 'message': 'Atualize a consulta para continuar.'}}, status=409)
            except PermissionError:
                return JsonResponse({'error': {'code': 'forbidden', 'message': 'Acesso não autorizado ou liberação revogada.'}}, status=403)
            except ObjectDoesNotExist:
                return JsonResponse({'error': {'code': 'not_found', 'message': 'Resultado não encontrado.'}}, status=404)
            except (ValueError, TypeError, KeyError) as exc:
                return JsonResponse({'error': {'code': 'invalid_request', 'message': 'Confira os filtros e a paginação.',
                                               'reason': str(exc)}}, status=400)
            except DatabaseError:
                return JsonResponse({'error': {'code': 'service_unavailable', 'message': 'Não foi possível consultar a base.'}}, status=503)
        return wrapped
    return decorate


@endpoint(['GET'])
def options(request):
    selected = context.from_query(request.user, request.GET)
    documents, _, exclusions = service.collect(request.user, selected)
    sources = []
    for source in context.SOURCES:
        matching = [d for d in documents if d['metadata']['source'] == source]
        released = sum(d['released'] for d in matching)
        sources.append({'id': source, 'availability': 'available' if released else 'pending_review' if matching else 'unavailable',
                        'mapped_documents': len(matching), 'quality_released_documents': released,
                        'reason': None if released else 'metadata_only' if source == 'datajud'
                        else 'reviewed_mapping_rights_and_quality_required'})
    return {'contract_version': 'analytical-context-v1', 'context': selected,
            'query_id': context.identity(selected), 'default_context': context.resolve(request.user, {}),
            'courts': sorted(context.permitted(request.user)), 'outcomes': list(context.OUTCOMES),
            'subject_codes': list(context.SUBJECTS),
            'sources': sources, 'unmapped_documents': exclusions['unmapped_documents']}


@endpoint(['POST'])
def snapshots(request):
    payload = json.loads(request.body)
    if not isinstance(payload, dict) or set(payload) != {'context'} or request.GET:
        raise ValueError('context_required')
    record = service.create(request.user, payload['context'])
    return service.manifest(record)


@endpoint(['GET'])
def detail(request, snapshot_id):
    if request.GET:
        raise ValueError('unknown_query_field')
    return service.manifest(service.read(request.user, snapshot_id))


@endpoint(['GET'])
def export(request, snapshot_id):
    if request.GET:
        raise ValueError('unknown_query_field')
    return service.manifest(service.read(request.user, snapshot_id), full=True)


@endpoint(['GET'])
def report(request, snapshot_id):
    if request.GET:
        raise ValueError('unknown_query_field')
    payload = service.manifest(service.read(request.user, snapshot_id), full=True)
    payload['context_json'] = json.dumps(payload['context'], ensure_ascii=False, sort_keys=True, indent=2)
    payload['generated_local'] = datetime.fromisoformat(payload['created_at']).astimezone(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M:%S (São Paulo)')
    names = {'decision_text': 'Textos de decisões', 'precedent': 'Precedentes', 'doctrine': 'Doutrina',
             'official_document': 'documento oficial', 'bibliographic_item': 'item bibliográfico',
             'decision_date': 'data da decisão', 'authority_validity': 'vigência da autoridade',
             'publication_date': 'data de publicação', 'ready': 'disponível', 'empty': 'vazio',
             'unavailable': 'indisponível', 'partial': 'parcial', 'released': 'liberada',
             'pending_or_unavailable': 'pendente ou indisponível'}
    payload['status_label'] = names.get(payload['status'], payload['status'])
    payload['quality_label'] = names.get(payload['quality']['state'], payload['quality']['state'])
    for name, population in payload['populations'].items():
        population['display_name'] = names[name]
        for field in ('unit', 'period_field', 'status'):
            population[field + '_label'] = names.get(population[field], population[field])
    exclusion_labels = {'unmapped_documents': 'Documentos sem mapeamento revisado', 'quality_blocked': 'Documentos bloqueados por qualidade',
                        'missing_text': 'Documentos sem texto processável', 'evidence_not_approved': 'Evidências sem revisão aprovada'}
    payload['exclusion_rows'] = [{'label': exclusion_labels.get(k, k), 'count': v} for k, v in payload['exclusions'].items()]
    for item in payload['items']:
        item['pipeline_json'] = json.dumps(item['pipeline'], ensure_ascii=False, sort_keys=True)
        item['coverage_json'] = json.dumps(item['coverage'], ensure_ascii=False, sort_keys=True)
        item['official_url'] = service.official_url(item['official_url'])
    template = Engine(dirs=[settings.BASE_DIR / 'templates']).get_template('nlp_report.html')
    return HttpResponse(template.render(Context(payload)), content_type='text/html; charset=utf-8')


@endpoint(['GET'])
def ranking(request, snapshot_id, resource, group_id=None):
    if resource not in ('theses', 'grounds'):
        raise ValueError('invalid_resource')
    return service.page(service.read(request.user, snapshot_id), resource, request.GET, group_id)
