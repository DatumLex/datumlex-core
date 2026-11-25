"""Authenticated evidence contract consumed by #115 and #129."""
import json
from functools import wraps

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import OuterRef, Subquery
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from src.db.models import NlpEvidence, NlpExtraction, NlpRevision, NlpSnapshot
from src.services import nlp_evidence as service
from src.services.corpus_publication import allowed_versions, require_reviewer, reviewer, version_available


def endpoint(methods):
    def decorate(fn):
        @require_http_methods(methods)
        @wraps(fn)
        def wrapped(request, **kwargs):
            try:
                return JsonResponse(fn(request, **kwargs))
            except service.Conflict as exc:
                return JsonResponse({'error': str(exc)}, status=409)
            except PermissionError:
                return JsonResponse({'error': 'forbidden'}, status=403)
            except ObjectDoesNotExist:
                return JsonResponse({'error': 'not_found'}, status=404)
            except (ValueError, TypeError, KeyError, ValidationError):
                return JsonResponse({'error': 'invalid_request'}, status=400)
        return wrapped
    return decorate


def body(request):
    value = json.loads(request.body)
    if not isinstance(value, dict):
        raise ValueError('object_required')
    return value


@endpoint(['GET'])
def extraction(request, extraction_id):
    require_reviewer(request.user)
    run = NlpExtraction.objects.get(pk=extraction_id)
    service.authorize(request.user, run.document)
    return {'id': str(run.pk), 'status': run.status, 'result_sha256': run.result_sha256,
            'previous_id': str(run.previous_id) if run.previous_id else None,
            'original_result': run.original_result}


@endpoint(['GET'])
def extraction_evidences(request, extraction_id):
    run = NlpExtraction.objects.get(pk=extraction_id)
    service.authorize(request.user, run.document)
    limit = int(request.GET.get('limit', 50))
    if not 1 <= limit <= 100:
        raise ValueError('invalid_limit')
    after = request.GET.get('after', '')
    evidence = run.evidences.all()
    admin = reviewer(request.user)
    if not admin:
        check_version(run)
        latest = NlpRevision.objects.filter(evidence_id=OuterRef("pk")).order_by("-number")
        evidence = evidence.annotate(current_state=Subquery(latest.values("state")[:1])).filter(current_state="approved")
    rows = list(evidence.filter(annotation_id__gt=after).order_by('annotation_id')[:limit + 1])
    items = [service.read_evidence(row, actor=request.user) for row in rows[:limit]]
    if not admin:
        items = [service.public_payload(item) for item in items
                 if item["review_status"] == "approved" and item["source_state"] == "available"]
    return {'extraction_id': str(run.pk), 'status': run.status,
            'ordering': 'annotation_id_ascending', 'ranking': None,
            'total': evidence.count(), 'items': items,
            'next_after': rows[limit - 1].annotation_id if len(rows) > limit else None,
            'consistency': 'Use evidence-snapshots to freeze reviews across pages and exports.'}


@endpoint(['GET'])
def detail(request, evidence_id):
    evidence = NlpEvidence.objects.get(pk=evidence_id)
    view = request.GET.get('view', 'effective')
    if view not in ('original', 'effective'):
        raise ValueError('invalid_view')
    revision = request.GET.get('revision')
    if revision is not None:
        revision = int(revision)
        if revision < 0 or view == 'original':
            raise ValueError('invalid_revision')
    if reviewer(request.user):
        return service.read_evidence(evidence, actor=request.user, original=view == 'original', revision=revision)
    if view != "effective" or revision is not None:
        raise PermissionError("legal_review_required")
    check_version(evidence.extraction)
    item = service.read_evidence(evidence, actor=request.user)
    if item["review_status"] != "approved" or item["source_state"] != "available":
        raise PermissionError("evidence_not_published")
    return service.public_payload(item)


def check_version(run):
    if not version_available(run.text_version, allowed_versions(ids=[run.text_version_id])):
        raise PermissionError("source_not_published")


@endpoint(['GET', 'POST'])
def revisions(request, evidence_id):
    if request.method == 'POST':
        payload = body(request)
        result = service.review(
            evidence_id, actor=request.user, expected_revision=payload['expected_revision'],
            action=payload['action'], reason=payload['reason'],
            request_key=request.headers['Idempotency-Key'], replacement=payload.get('replacement'),
        )
        return {'id': str(result.pk), 'revision': result.number, 'status': result.state}
    evidence = NlpEvidence.objects.get(pk=evidence_id)
    require_reviewer(request.user)
    service.authorize(request.user, evidence.extraction.document)
    after = int(request.GET.get('after', 0))
    limit = int(request.GET.get('limit', 50))
    if after < 0 or not 1 <= limit <= 100:
        raise ValueError('invalid_pagination')
    rows = list(evidence.revisions.filter(number__gt=after).order_by('number')[:limit + 1])
    return {'items': [{'id': str(row.pk), 'revision': row.number, 'action': row.action,
                      'status': row.state, 'reviewer_id': row.reviewer_id,
                      'reviewed_at': row.created_at.isoformat(), 'reason': row.reason,
                      'before': row.before, 'after': row.after} for row in rows[:limit]],
            'next_after': rows[limit - 1].number if len(rows) > limit else None}


@endpoint(['POST'])
def snapshots(request):
    require_reviewer(request.user)
    payload = body(request)
    record = service.snapshot(actor=request.user, evidence_ids=payload['evidence_ids'], context=payload['context'])
    return service.read_snapshot(record, request.user)


@endpoint(['GET'])
def snapshot_detail(request, snapshot_id):
    require_reviewer(request.user)
    return service.read_snapshot(NlpSnapshot.objects.get(pk=snapshot_id), request.user)
