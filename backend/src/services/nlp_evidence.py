"""Persistence adapter for #109 v0.1.0; reviews never rewrite pipeline outputs."""
from copy import deepcopy
from math import isfinite
from uuid import UUID

from django.db import transaction
from django.db.models import Max

from src.db.models import (
    NlpDocument,
    NlpEvidence,
    NlpExtraction,
    NlpRevision,
    NlpSnapshot,
    NlpSourceObservation,
    NlpTextVersion,
)
from src.nlp.contracts import bytes_hash, fingerprint, validate_annotation, validate_result


class Conflict(ValueError):
    pass


def annotation_check(value, text):
    try:
        validate_annotation(value, text)
        if value.get('review_status') != 'pending':
            raise ValueError('review_status_is_separate')
        score = value['confidence']['score']
        if score is not None and (type(score) not in (int, float) or not isfinite(score) or not 0 <= score <= 1):
            raise ValueError('invalid_confidence')
        fingerprint(value)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('malformed_annotation') from exc


def authorize(actor, document, write=False):
    if not actor.is_authenticated or not actor.is_active or not actor.approved or actor.must_change_password:
        raise PermissionError('inactive_account')
    if not actor.support and not actor.courts.filter(pk=document.court).exists():
        raise PermissionError('court_forbidden')
    if write and actor.role not in ('Master', 'Admin'):
        raise PermissionError('reviewer_role_required')


@transaction.atomic
def persist_result(result, text, *, request_key, previous_id=None, reason=''):
    """Caller supplies verified source text; command uses #109's artifact reader."""
    result = deepcopy(result)
    request_key = UUID(str(request_key))
    try:
        validate_result(result, text)
        digest = result['result_sha256']
        if digest != fingerprint({k: v for k, v in result.items() if k != 'result_sha256'}):
            raise ValueError('result_hash_mismatch')
        source = result['source']
        if not result['document_id'] or source['document_id'] != result['document_id']:
            raise ValueError('document_identity_mismatch')
        if source['court'] not in ('STJ', 'TJDFT'):
            raise ValueError('unsupported_court')
        if result['text']['offset_unit'] != 'unicode_code_point':
            raise ValueError('unsupported_offsets')
        if result['status'] not in ('completed', 'partial', 'failed', 'missing_text'):
            raise ValueError('invalid_result_status')
        if result['status'] in ('failed', 'missing_text') and result['annotations']:
            raise ValueError('failed_result_has_evidence')
        if result['status'] in ('completed', 'partial') and not text:
            raise ValueError('missing_text')
        for item in result['annotations']:
            annotation_check(item, text)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('malformed_result') from exc
    document, _ = NlpDocument.objects.get_or_create(
        source_key=result['document_id'], defaults={'court': source['court']},
    )
    # Serializes idempotent ingestion and source observation against this document.
    document = NlpDocument.objects.select_for_update().get(pk=document.pk)
    if document.court != source['court']:
        raise Conflict('document_court_changed')
    existing = NlpExtraction.objects.filter(request_key=request_key).first()
    if existing:
        if (existing.result_sha256 != digest or str(existing.previous_id or '') != str(previous_id or '')
                or existing.reason != reason):
            raise Conflict('idempotency_key_reused')
        return existing
    previous = None
    if previous_id:
        previous = NlpExtraction.objects.get(pk=previous_id, document=document)
        if not reason.strip():
            raise ValueError('reprocessing_reason_required')
    version = None
    if text is not None:
        version, _ = NlpTextVersion.objects.get_or_create(
            document=document,
            fingerprint=fingerprint({'source': source, 'representation': result['text']}),
            defaults={'text': text, 'sha256': bytes_hash(text.encode('utf-8')),
                      'source': source, 'representation': result['text']},
        )
        if version.text != text:
            raise Conflict('text_identity_collision')
    observation = NlpSourceObservation.objects.create(
        document=document, text_version=version,
        sequence=(document.nlpsourceobservation_set.aggregate(n=Max('sequence'))['n'] or 0) + 1,
        state='available' if text is not None else 'unavailable',
        source_url=source.get('source_url') or '', details={'errors': result['errors']},
    )
    run = NlpExtraction.objects.create(
        document=document, text_version=version, observation=observation,
        request_key=request_key, result_sha256=digest, original_result=result,
        status=result['status'], previous=previous, reason=reason,
    )
    NlpEvidence.objects.bulk_create([
        NlpEvidence(extraction=run, annotation_id=a['id'], original=a, sha256=fingerprint(a))
        for a in result['annotations']
    ])
    return run


@transaction.atomic
def observe_source(document_id, *, state, source_url='', details=None):
    if state not in ('available', 'changed', 'not_found', 'removed', 'temporarily_unavailable', 'restricted'):
        raise ValueError('invalid_source_state')
    document = NlpDocument.objects.select_for_update().get(pk=document_id)
    return NlpSourceObservation.objects.create(
        document=document, state=state, source_url=source_url, details=details or {},
        sequence=(document.nlpsourceobservation_set.aggregate(n=Max('sequence'))['n'] or 0) + 1,
    )


TRANSITIONS = {
    'pending': {'approve', 'correct', 'reject'},
    'approved': {'correct', 'reject', 'reopen'},
    'corrected': {'approve', 'correct', 'reject', 'reopen'},
    'rejected': {'reopen'},
}
STATES = {'approve': 'approved', 'correct': 'corrected', 'reject': 'rejected', 'reopen': 'pending'}


@transaction.atomic
def review(evidence_id, *, actor, expected_revision, action, reason, request_key, replacement=None):
    evidence = NlpEvidence.objects.select_for_update(of=('self',)).select_related(
        'extraction__document', 'extraction__text_version',
    ).get(pk=evidence_id)
    authorize(actor, evidence.extraction.document, write=True)
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError('invalid_expected_revision')
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('reason_required')
    key = UUID(str(request_key))
    command_hash = fingerprint({'actor': actor.pk, 'expected_revision': expected_revision,
                                'action': action, 'reason': reason, 'replacement': replacement})
    replay = evidence.revisions.filter(request_key=key).first()
    if replay:
        if replay.request_sha256 != command_hash:
            raise Conflict('idempotency_key_reused')
        return replay
    latest = evidence.revisions.order_by('-number').first()
    number = latest.number if latest else 0
    state = latest.state if latest else 'pending'
    if expected_revision != number:
        raise Conflict('stale_revision')
    if action not in TRANSITIONS[state]:
        raise ValueError('invalid_transition')
    before = deepcopy(latest.after if latest else evidence.original)
    if action == 'correct':
        if not isinstance(replacement, dict) or replacement == before:
            raise ValueError('changed_replacement_required')
        after = deepcopy(replacement)
        # Extraction provenance/confidence are machine observations, not human edits.
        for key_name in ('id', 'method', 'confidence', 'label_status', 'review_status'):
            if after.get(key_name) != before.get(key_name):
                raise ValueError('immutable_annotation_identity')
        if set(after) != set(before):
            raise ValueError('annotation_fields_changed')
    else:
        if replacement is not None:
            raise ValueError('replacement_only_for_correction')
        after = before
    version = evidence.extraction.text_version
    if bytes_hash(version.text.encode('utf-8')) != version.sha256:
        raise ValueError('stored_text_hash_mismatch')
    annotation_check(after, version.text)
    return NlpRevision.objects.create(
        evidence=evidence, number=number + 1, action=action, state=STATES[action],
        reviewer=actor, reason=reason.strip(), before=before, after=after,
        request_key=UUID(str(request_key)), request_sha256=command_hash,
    )


def read_evidence(evidence, *, actor, revision=None, original=False):
    run = evidence.extraction
    authorize(actor, run.document)
    revisions = evidence.revisions
    selected = None
    if not original and revision != 0:
        selected = revisions.get(number=revision) if revision is not None else revisions.order_by('-number').first()
    version = run.text_version
    observation = run.document.nlpsourceobservation_set.order_by('-sequence').first()
    return {
        'contract_version': 'evidence-read/1.0', 'id': str(evidence.pk),
        'document_id': run.document.source_key, 'court': run.document.court,
        'extraction_id': str(run.pk), 'result_sha256': run.result_sha256,
        'text_version_id': str(version.pk), 'text_sha256': version.sha256,
        'source': version.source, 'pipeline': run.original_result['pipeline'],
        'original': evidence.original, 'effective': selected.after if selected else evidence.original,
        'revision': selected.number if selected else 0,
        'revision_id': str(selected.pk) if selected else None,
        'review_status': selected.state if selected else 'pending',
        'has_corrections': revisions.filter(action='correct', number__lte=selected.number).exists() if selected else False,
        'source_state': observation.state, 'source_checked_at': observation.created_at.isoformat(),
        'source_observation_id': str(observation.pk),
        'coverage': run.original_result['coverage'], 'evaluation': run.original_result['evaluation'],
        'warnings': run.original_result['warnings'], 'extraction_status': run.status,
    }


@transaction.atomic
def snapshot(*, actor, evidence_ids, context):
    if not isinstance(context, dict) or not isinstance(evidence_ids, list) or not 1 <= len(evidence_ids) <= 500:
        raise ValueError('invalid_snapshot_request')
    ids = [UUID(str(value)) for value in evidence_ids]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate_evidence')
    # Lock order shared with review writers; materialize before reading any revisions.
    rows = list(NlpEvidence.objects.select_for_update().filter(pk__in=ids).order_by('pk'))
    if len(rows) != len(ids):
        raise ValueError('unknown_evidence')
    documents = sorted({row.extraction.document_id for row in rows})
    list(NlpDocument.objects.select_for_update().filter(pk__in=documents).order_by('pk'))
    indexed = {row.pk: row for row in rows}
    payload = {'contract_version': 'evidence-snapshot/1.0', 'context': deepcopy(context),
               'context_validation': 'caller_supplied_pending_165',
               'items': [read_evidence(indexed[pk], actor=actor) for pk in ids],
               'counting_unit': 'evidence', 'count': len(ids)}
    return NlpSnapshot.objects.create(owner=actor, payload=payload, sha256=fingerprint(payload))


def read_snapshot(record, actor):
    # Re-evaluate current rights even when serving an old frozen payload.
    if record.owner_id != actor.pk and not actor.support:
        raise PermissionError('snapshot_owner_required')
    if record.payload.get('contract_version') == 'nlp-dashboard/1.0':
        # The older route must not bypass #115 release/context reauthorization.
        from src.services import nlp_dashboard
        nlp_dashboard.read(actor, record.pk)
    for court in {item['court'] for item in record.payload['items']}:
        authorize(actor, NlpDocument(court=court))
    return {'id': str(record.pk), 'created_at': record.created_at.isoformat(),
            'sha256': record.sha256, **record.payload}
