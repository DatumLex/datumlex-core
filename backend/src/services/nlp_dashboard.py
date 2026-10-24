"""Frozen, source-linked NLP views. No implicit quality or source-rights approval."""
from copy import deepcopy
from datetime import date, timedelta
from urllib.parse import urlparse

from django.conf import settings
from django.core import signing
from django.db import connection, transaction
from django.utils import timezone

from src.db.models import NlpExtraction, NlpSnapshot
from src.nlp.contracts import bytes_hash, fingerprint
from src.services import analytical_context as context_service
from src.services import nlp_evidence

CONTRACT = 'nlp-dashboard/1.0'
DISCLAIMER = 'Frequência documental não representa probabilidade de vitória nem autoridade jurídica.'
SOURCE_TYPES = {'tjdft_jurisprudence': 'decision_text', 'stj_jurisprudence': 'decision_text',
                'stj_precedent': 'precedent', 'bdjur_doctrine': 'doctrine'}
PERIOD_FIELDS = {'decision_text': 'decision_date', 'precedent': 'authority_validity', 'doctrine': 'publication_date'}


def official_url(value):
    """Never manufacture URLs or render untrusted schemes/third-party links."""
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    host = (parsed.hostname or '').lower()
    if parsed.scheme == 'https' and not parsed.username and not parsed.password and any(
        host == domain or host.endswith('.' + domain) for domain in ('stj.jus.br', 'tjdft.jus.br')
    ):
        return value
    return None


def applies(metadata, court, context):
    source = metadata['source']
    kind = SOURCE_TYPES.get(source)
    if kind is None or source not in context['sources']:
        return False
    if kind == 'decision_text' and court not in context['courts']:
        return False
    if not set(metadata['subject_codes']) & set(context['subject_codes']):
        return False
    if kind == 'precedent':
        # #118 owns validity. Missing reviewed validity never becomes a match.
        return bool(metadata.get('temporal_approval_reference') and metadata.get('valid_from')
                    and metadata['valid_from'] <= context['end']
                    and (not metadata.get('valid_to') or metadata['valid_to'] >= context['start']))
    value = metadata.get(PERIOD_FIELDS[kind])
    if value and (not isinstance(value, str) or date.fromisoformat(value).isoformat() != value):
        raise ValueError('invalid_catalog_date')
    return bool(value and context['start'] <= value <= context['end'])


def collect(actor, context):
    """Only a reviewed server-side catalog may supply missing #104/#166 mappings.

    Catalog entries bind exact extraction/text IDs and pipeline fingerprints.
    An absent mapping/decision is disclosed, never guessed from process metadata.
    """
    catalog = getattr(settings, 'NLP_DASHBOARD_CATALOG', {})
    releases = getattr(settings, 'NLP_DASHBOARD_RELEASES', {})
    max_documents = getattr(settings, 'NLP_DASHBOARD_MAX_DOCUMENTS', 10000)
    runs = NlpExtraction.objects.filter(document__court__in=context['courts']).select_related('document', 'text_version')
    if not context['sources'] or not context['subject_codes']:
        return [], [], {'unmapped_documents': 0, 'quality_blocked': 0, 'missing_text': 0}
    if runs.values('document_id').distinct().count() > max_documents:
        raise nlp_evidence.Conflict('snapshot_capacity_exceeded')
    documents, evidence, exclusions = [], [], {'unmapped_documents': 0, 'quality_blocked': 0, 'missing_text': 0,
                                              'evidence_not_approved': 0}
    seen = set()
    # A catalog must select an exact run. Do not choose a failed/newest attempt.
    for run in runs.order_by('document_id', 'created_at', 'id'):
        key = run.document.source_key
        metadata = catalog.get(key)
        if not metadata:
            if key not in seen:
                exclusions['unmapped_documents'] += 1
                seen.add(key)
            continue
        if metadata.get('extraction_id') != str(run.pk):
            continue
        if not metadata.get('mapping_approval_reference') or not applies(metadata, run.document.court, context):
            continue
        kind = SOURCE_TYPES[metadata['source']]
        document = {'id': key, 'court': run.document.court, 'kind': kind, 'metadata': deepcopy(metadata),
                    'has_text': run.text_version_id is not None, 'processed': run.status == 'completed', 'released': False}
        documents.append(document)
        if run.text_version is None or run.status != 'completed':
            exclusions['missing_text'] += 1
            continue
        release = releases.get(metadata.get('release_id'), {})
        valid = (release.get('state') == 'released' and release.get('approval_reference')
                 and release.get('benchmark_version') and release.get('rights_approval_reference')
                 and release.get('pipeline_sha256') == fingerprint(run.original_result['pipeline'])
                 and release.get('source') == metadata['source']
                 and metadata.get('text_version_id') == str(run.text_version_id)
                 and release.get('inclusion_policy') == 'human_approved_only'
                 and release.get('tasks') == ['LEGAL_GROUND', 'LEGAL_THESIS'])
        if not valid:
            exclusions['quality_blocked'] += 1
            continue
        document['released'] = True
        document['release'] = deepcopy(release)
        if kind == 'decision_text' and metadata.get('outcome', 'unknown') not in context['outcomes']:
            continue
        if bytes_hash(run.text_version.text.encode('utf-8')) != run.text_version.sha256:
            raise ValueError('stored_text_hash_mismatch')
        for row in run.evidences.select_related('extraction__document', 'extraction__text_version').order_by('annotation_id'):
            item = nlp_evidence.read_evidence(row, actor=actor)
            nlp_evidence.annotation_check(item['effective'], run.text_version.text)
            if item['review_status'] != 'approved':
                exclusions['evidence_not_approved'] += 1
                continue
            item['population'] = kind
            item['source_id'] = metadata['source']
            item['document_metadata'] = deepcopy(metadata)
            item['official_url'] = official_url(item['source'].get('source_url'))
            item['quality_release'] = deepcopy(release)
            evidence.append(item)
    return documents, evidence, exclusions


def aggregate(items, population, label):
    """Exact-literal groups only; no semantic equivalence or adoption inference."""
    groups = {}
    for item in items:
        annotation = item['effective']
        if item['population'] != population or label not in annotation['labels']:
            continue
        segments = annotation['segments']
        key = fingerprint({'label': label, 'passages': [s['text'] for s in segments]})
        group = groups.setdefault(key, {'id': key, 'label': ' […] '.join(s['text'] for s in segments),
                                       'documents': set(), 'evidence_ids': [], 'uncertainty': ['frequency_not_adoption']})
        group['documents'].add(item['document_id'])
        group['evidence_ids'].append(item['id'])
    result = []
    for value in groups.values():
        documents = value.pop('documents')
        value['document_count'] = len(documents)
        value['evidence_count'] = len(value['evidence_ids'])
        result.append(value)
    return sorted(result, key=lambda value: (-value['document_count'], value['id']))


def materialize(context, documents, evidence, exclusions, *, data_mode='live'):
    populations = {}
    for kind in ('decision_text', 'precedent', 'doctrine'):
        selected = [d for d in documents if d['kind'] == kind]
        released = [d for d in selected if d['released']]
        displayed = [d for d in released if kind != 'decision_text' or d['metadata'].get('outcome', 'unknown') in context['outcomes']]
        population = {'unit': 'bibliographic_item' if kind == 'doctrine' else 'official_document',
                      'period_field': PERIOD_FIELDS[kind], 'court_filter_applied': kind == 'decision_text',
                      'outcome_filter_applied': kind == 'decision_text', 'documents_in_scope': len(selected),
                      'documents_with_text': sum(d.get('has_text', False) for d in selected),
                      'documents_processed': sum(d.get('processed', False) for d in selected),
                      'documents_quality_released': len(released), 'denominator': len(displayed)}
        for resource, label in [('theses', 'LEGAL_THESIS'), ('grounds', 'LEGAL_GROUND')]:
            population[resource] = aggregate(evidence, kind, label)
        population['status'] = 'ready' if released else 'unavailable'
        if selected and released and not displayed:
            population['status'] = 'empty'
        if not context['sources'] or not context['subject_codes']:
            population['status'] = 'empty'
        population['reason'] = None if released else 'reviewed_quality_and_source_mapping_required'
        populations[kind] = population
    bindings = {d['metadata']['release_id']: d['release'] for d in documents if d['released']}
    fixture_ids = sorted({d['metadata']['fixture_id'] for d in documents if d['metadata'].get('fixture_id')})
    if fixture_ids:
        data_mode = 'fixture'
    return {'contract_version': CONTRACT, 'context': context, 'query_id': context_service.identity(context),
            'data_mode': data_mode, 'fixture_ids': fixture_ids, 'disclaimer': DISCLAIMER, 'items': evidence, 'populations': populations,
            'exclusions': exclusions, 'status': 'empty' if not context['sources'] or not context['subject_codes'] else 'partial' if evidence else 'unavailable',
            'release_bindings': bindings,
            'warnings': ['loaded_corpus_not_judicial_census', 'exact_literal_grouping_not_semantic_equivalence'],
            'quality': {'state': 'released' if bindings else 'pending_or_unavailable',
                        'reason': None if bindings else 'reviewed_quality_and_source_mapping_required'},
            'ranking_policy': 'distinct-document-exact-literal-v1',
            'context_validation': 'server_validated_analytical-context-v1',
            'pdf_contract': 'Render this complete immutable payload; never query latest evidence.'}


@transaction.atomic
def create(actor, supplied):
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    context = context_service.resolve(actor, supplied)
    documents, evidence, exclusions = collect(actor, context)
    payload = materialize(context, documents, evidence, exclusions)
    return NlpSnapshot.objects.create(owner=actor, payload=payload, sha256=fingerprint(payload))


def read(actor, snapshot_id):
    record = NlpSnapshot.objects.get(pk=snapshot_id)
    if record.owner_id != actor.pk and not actor.support:
        raise PermissionError('snapshot_owner_required')
    if record.payload.get('contract_version') != CONTRACT:
        raise ValueError('wrong_snapshot_contract')
    context_service.authorize(actor, record.payload['context'])
    if record.created_at + timedelta(hours=getattr(settings, 'NLP_DASHBOARD_TTL_HOURS', 24)) < timezone.now():
        raise nlp_evidence.Conflict('snapshot_unavailable')
    if fingerprint(record.payload) != record.sha256:
        raise ValueError('snapshot_integrity_error')
    # Rights/quality revocation overrides historical access; frozen values never change.
    releases = getattr(settings, 'NLP_DASHBOARD_RELEASES', {})
    for release_id, decision in record.payload.get('release_bindings', {}).items():
        if releases.get(release_id) != decision:
            raise PermissionError('release_revoked_or_changed')
    return record


def manifest(record, full=False):
    payload = deepcopy(record.payload)
    if not full:
        payload.pop('items')
        for population in payload['populations'].values():
            for key in ('theses', 'grounds'):
                population[key + '_count'] = len(population.pop(key))
    return {'snapshot_id': str(record.pk), 'sha256': record.sha256,
            'created_at': record.created_at.isoformat(), **payload}


def page(record, resource, query, group_id=None):
    if set(query) - {'population', 'order', 'limit', 'cursor'} or any(len(query.getlist(k)) != 1 for k in query):
        raise ValueError('invalid_pagination_query')
    population = query.get('population', 'decision_text')
    if population not in record.payload['populations']:
        raise ValueError('invalid_population')
    order = query.get('order', 'evidence_id' if group_id else '-document_count')
    if order not in (('evidence_id',) if group_id else ('-document_count', 'document_count', 'label')):
        raise ValueError('invalid_order')
    limit = int(query.get('limit', 20))
    if not 1 <= limit <= 100:
        raise ValueError('invalid_limit')
    groups = deepcopy(record.payload['populations'][population][resource])
    if group_id:
        group = next((g for g in groups if g['id'] == group_id), None)
        if group is None:
            raise NlpSnapshot.DoesNotExist()
        rows = sorted((i for i in record.payload['items'] if i['id'] in group['evidence_ids']), key=lambda i: i['id'])
    else:
        rows = sorted(groups, key=lambda g: ((-g['document_count'] if order == '-document_count' else g['document_count'])
                                             if order != 'label' else g['label'], g['id']))
        for rank, row in enumerate(rows, 1):
            row['rank'] = rank
            row.pop('evidence_ids')
            denominator = record.payload['populations'][population]['denominator']
            row['document_share'] = row['document_count'] / denominator if denominator else None
    binding = [str(record.pk), population, resource, group_id, order]
    offset = 0
    if query.get('cursor'):
        try:
            cursor = signing.loads(query['cursor'], salt=CONTRACT)
            if cursor['binding'] != binding or type(cursor['offset']) is not int or cursor['offset'] < 0:
                raise ValueError('invalid_cursor')
            offset = cursor['offset']
        except (signing.BadSignature, KeyError, TypeError) as exc:
            raise ValueError('invalid_cursor') from exc
    next_offset = offset + limit
    return {'snapshot_id': str(record.pk), 'query_id': record.payload['query_id'], 'population': population,
            'items': rows[offset:next_offset], 'order': order, 'total_items': len(rows),
            'next_cursor': signing.dumps({'binding': binding, 'offset': next_offset}, salt=CONTRACT)
            if next_offset < len(rows) else None}
