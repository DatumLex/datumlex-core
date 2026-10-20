from functools import wraps

from django.db import DatabaseError, connection
from django.db.models import Count, Max, Prefetch, Q
from django.db.models.functions import TruncQuarter
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from src.db.models import DecisionAssessment, DimSubject, FactProcess, LegalReference, ProcessMovement
from src.services.outcomes import CODES, classify, summarize
from src.services.statistics_service import (
    InvalidQuery,
    filtered_processes,
    instance_series,
    metadata,
    metrics,
)


def endpoint(function):
    @require_GET
    @wraps(function)
    def wrapped(request):
        try:
            result = function(request)
            response = JsonResponse(result)
            response["Cache-Control"] = "no-store"
            return response
        except InvalidQuery as exc:
            return JsonResponse({"error": {"code": "invalid_query", "message": str(exc)}}, status=400)
        except DatabaseError:
            return JsonResponse(
                {
                    "error": {
                        "code": "database_unavailable",
                        "message": "Database unavailable; verify migrations and connection.",
                    }
                },
                status=503,
            )

    return wrapped


@endpoint
def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    # Verify that migrations have actually been applied too.
    FactProcess.objects.exists()
    return {"status": "ok", "service": "datumlex-backend", "database": connection.vendor}


@endpoint
def scope(request):
    query, selected = filtered_processes(request.GET)
    return {
        "metadata": metadata(query, selected),
        "subjects": list(
            DimSubject.objects.filter(factprocess__in=query)
            .distinct()
            .order_by("code")
            .values("code", "name")
        ),
    }


@endpoint
def statistics(request):
    query, selected = filtered_processes(request.GET)
    return {
        "status": "partial" if query.exists() else "empty",
        "metrics": metrics(query),
        "metadata": metadata(query, selected),
    }


@endpoint
def distribution(request):
    query, selected = filtered_processes(request.GET)
    result = summarize(query)
    denominator = result["binary_denominator"]
    series = (
        [
            {"outcome": key, "count": result[key], "rate": result[key] / denominator}
            for key in ("granted", "denied")
            if selected["outcome"] in {"all", key}
        ]
        if denominator
        else []
    )
    return {
        "status": "partial" if denominator else "unavailable",
        "series": series,
        "denominator": denominator,
        "excluded": result["excluded"],
        "metadata": metadata(query, selected),
    }


@endpoint
def instances(request):
    query, selected = filtered_processes(request.GET)
    return {
        "status": "partial" if query.exists() else "empty",
        "series": instance_series(query),
        "metric": "process_records_by_filing_quarter",
        "outcome_filter_applied": False,
        "metadata": metadata(query, selected),
    }


@endpoint
def processes(request):
    query, selected = filtered_processes(request.GET)
    try:
        page, size = int(request.GET.get("page", 1)), int(request.GET.get("page_size", 25))
        if page < 1 or not 1 <= size <= 100:
            raise ValueError
    except ValueError:
        raise InvalidQuery("page must be positive; page_size must be 1..100") from None
    count = query.count()
    rows = (
        query.select_related("time", "process_class", "organization", "degree_dimension")
        .defer("raw_payload", "payload_hash")
        .prefetch_related(
            "subjects",
            Prefetch(
                "movements",
                queryset=ProcessMovement.objects.filter(code__in=CODES).only(
                    "id", "process_id", "code", "occurred_at"
                ),
            ),
        )
        .order_by("id")[(page - 1) * size : page * size]
    )
    return {
        "count": count,
        "page": page,
        "page_size": size,
        "outcome_filter_applied": False,
        "results": [
            {
                "id": row.pk,
                "source_id": row.source_id,
                "court": row.court,
                "degree": row.degree,
                "filing_date": row.time.date,
                "class": {"code": row.process_class.code, "name": row.process_class.name},
                "organization": {"code": row.organization.code, "name": row.organization.name},
                "subjects": [{"code": subject.code, "name": subject.name} for subject in row.subjects.all()],
                **classify(row),
            }
            for row in rows
        ],
        "metadata": metadata(query, selected),
    }


@endpoint
def alignment(request):
    _, selected = filtered_processes(request.GET)
    if selected["court"] != "TJDFT":
        raise InvalidQuery("Jurisprudential alignment is scoped to local TJDFT decisions")
    assessments = DecisionAssessment.objects.filter(
        local_decision__court="TJDFT",
        decision_date__range=[selected["start"], selected["end"]],
        review_state=DecisionAssessment.REVIEW_APPROVED,
        reference__approved=True,
        reference__reference_type=LegalReference.PRECEDENT,
        reference__source_institution="STJ",
    ).select_related("local_decision__process_dimension", "reference")
    if selected["subject"]:
        assessments = assessments.filter(local_decision__subjects__code=selected["subject"])
    assessments = assessments.order_by()
    period_assessments = DecisionAssessment.objects.filter(
        local_decision__court="TJDFT", decision_date__range=[selected["start"], selected["end"]],
        reference__reference_type=LegalReference.PRECEDENT, reference__source_institution="STJ",
    )
    if selected["subject"]:
        period_assessments = period_assessments.filter(local_decision__subjects__code=selected["subject"])
    counts = assessments.aggregate(
        validated_links=Count("pk", distinct=True),
        local_decisions=Count("local_decision_id", distinct=True),
        aligned=Count("pk", filter=Q(relation=DecisionAssessment.ALIGNED), distinct=True),
        divergent=Count("pk", filter=Q(relation=DecisionAssessment.DIVERGENT), distinct=True),
        distinguished=Count("pk", filter=Q(relation=DecisionAssessment.DISTINGUISHED), distinct=True),
        uncertain=Count("pk", filter=Q(relation=DecisionAssessment.UNCERTAIN), distinct=True),
    )
    comparable = counts["aligned"] + counts["divergent"]
    trend = list(
        assessments.annotate(period=TruncQuarter("decision_date"))
        .values("period")
        .annotate(
            aligned=Count("pk", filter=Q(relation=DecisionAssessment.ALIGNED), distinct=True),
            divergent=Count("pk", filter=Q(relation=DecisionAssessment.DIVERGENT), distinct=True),
            distinguished=Count("pk", filter=Q(relation=DecisionAssessment.DISTINGUISHED), distinct=True),
            uncertain=Count("pk", filter=Q(relation=DecisionAssessment.UNCERTAIN), distinct=True),
        )
        .order_by("period")
    )
    rows = assessments.order_by("-decision_date", "-id")[:100]
    theses = list(
        assessments.values(
            "reference_id",
            "reference__identifier",
            "reference__title",
            "reference__thesis",
            "reference__source_url",
            "reference__source_locator",
        )
        .annotate(
            validated_links=Count("pk", distinct=True),
            local_decisions=Count("local_decision_id", distinct=True),
        )
        .order_by("-validated_links", "reference__title")[:20]
    )
    source_theses = list(
        LegalReference.objects.filter(
            reference_type=LegalReference.PRECEDENT,
            source_institution="STJ",
        )
        .order_by("title", "identifier")
        .values(
            "id", "identifier", "title", "thesis", "source_name", "source_url",
            "source_locator", "approved", "approval_reference", "related_decisions",
        )[:100]
    )
    reviewed_thesis_counts = {
        row["reference_id"]: row
        for row in theses
    }
    for thesis in source_theses:
        counts_for_thesis = reviewed_thesis_counts.get(thesis["id"], {})
        thesis["validated_links"] = counts_for_thesis.get("validated_links", 0)
        thesis["local_decisions"] = counts_for_thesis.get("local_decisions", 0)
    references = list(
        LegalReference.objects.filter(approved=True)
        .order_by("source_institution", "source_name", "identifier")
        .values(
            "reference_type", "source_institution", "identifier", "title", "authority", "source_name",
            "source_url", "source_locator", "approval_reference", "published_at", "imported_at",
        ).distinct()[:200]
    )
    return {
        "status": "available" if counts["validated_links"] else "empty",
        "metrics": {
            **counts,
            "comparable_links": comparable,
            "adherence_rate": counts["aligned"] / comparable if comparable else None,
            "possible_divergence_rate": counts["divergent"] / comparable if comparable else None,
        },
        "trend": [
            {**row, "period": row["period"].isoformat()[:10]}
            for row in trend
        ],
        "assessments": [
            {
                "local_source_id": row.local_decision.source_id,
                "local_process_number": row.local_decision.number_process,
                "decision_date": row.decision_date,
                "relation": row.relation,
                "rationale": row.rationale,
                "evidence_excerpt": row.evidence_excerpt,
                "evidence_locator": row.evidence_locator,
                "reviewer": row.reviewer,
                "approval_reference": row.approval_reference,
                "reference": {
                    "type": row.reference.reference_type,
                    "source_institution": row.reference.source_institution,
                    "identifier": row.reference.identifier,
                    "title": row.reference.title,
                    "thesis": row.reference.thesis,
                    "authority": row.reference.authority,
                    "source_name": row.reference.source_name,
                    "source_url": row.reference.source_url,
                    "source_locator": row.reference.source_locator,
                    "published_at": row.reference.published_at,
                    "approval_reference": row.reference.approval_reference,
                },
            }
            for row in rows
        ],
        "theses": theses,
          "source_theses": source_theses,
        "metadata": {
            "scope": {**selected, "date_field": "decision_date", "court": "TJDFT"},
            "source": "Corpus aprovado e avaliações revisadas; fontes citadas por registro.",
            "coverage": "Somente vínculos importados e validados no corpus local. A ausência de vínculo não significa ausência de precedente aplicável. Exibidos até 100 vínculos; indicadores abrangem todos os vínculos validados no período.",
            "limitations": [
                "Aderência e possível divergência refletem avaliações humanas validadas, não classificação automática.",
                "Vínculos pendentes, não revisados, incertos e fontes não aprovadas não entram nos indicadores.",
                "Distinguishing justificado é informado separadamente e não contado como aderência nem divergência.",
                "Indicadores são por vínculo decisão-precedente/doutrina, não por processo único nem por total de decisões do TJDFT.",
                "Uma possível divergência é sinal para revisão jurídica, não conclusão sobre erro ou descumprimento.",
            ],
            "approved_references": {
                "precedents": LegalReference.objects.filter(approved=True, reference_type=LegalReference.PRECEDENT, source_institution="STJ").count(),
                "doctrine": LegalReference.objects.filter(approved=True, reference_type=LegalReference.DOCTRINE, source_institution="BDJur").count(),
            },
            "last_corpus_import": LegalReference.objects.filter(approved=True).aggregate(last=Max("imported_at"))["last"],
            "review_queue": {
                "pending_or_unreviewed": period_assessments.exclude(review_state=DecisionAssessment.REVIEW_APPROVED).count(),
                "approved_assessments_with_unapproved_reference": period_assessments.filter(
                    review_state=DecisionAssessment.REVIEW_APPROVED, reference__approved=False
                ).count(),
            },
            "sources": references,
            "source_list_limit": 200,
        },
    }
