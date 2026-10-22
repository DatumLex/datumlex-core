from functools import wraps

from django.db import DatabaseError, connection
from django.db.models import Count, Max, Prefetch, Q
from django.db.models.functions import TruncQuarter
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from src.db.models import (
    CrossSourceLinkCandidate,
    DecisionAssessment,
    DimSubject,
    FactProcess,
    LegalReference,
    PangeaImportRun,
    ProcessMovement,
)
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
            DimSubject.objects.filter(factprocess__court=selected["court"])
            .annotate(record_count=Count("factprocess", distinct=True))
            .filter(record_count__gt=0)
            .order_by("code")
            .values("code", "name", "record_count")
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
    source_theses_query = LegalReference.objects.filter(
        reference_type=LegalReference.PRECEDENT,
        source_institution="STJ",
    ).order_by("-imported_at", "-id").values(
        "id", "identifier", "title", "thesis", "source_name", "source_url",
        "source_locator", "approved", "approval_reference", "related_decisions",
        "source_updated_at",
    )
    source_theses = []
    reviewed_thesis_counts = {
        row["reference_id"]: row
        for row in theses
    }
    candidate_scope = CrossSourceLinkCandidate.objects.filter(
        reference__reference_type=LegalReference.PRECEDENT,
        reference__source_institution="STJ",
    )
    if selected["subject"]:
        candidate_scope = candidate_scope.filter(local_decision__subjects__code=selected["subject"])
    matched_by_reference = {
        row["reference_id"]: row["matched"]
        for row in candidate_scope.filter(
            local_decision__isnull=False,
            review_status__in=[CrossSourceLinkCandidate.PENDING, CrossSourceLinkCandidate.CONFIRMED],
        ).values("reference_id").annotate(matched=Count("local_decision_id", distinct=True))
    }
    unresolved_by_reference = {
        row["reference_id"]: row["unresolved"]
        for row in candidate_scope.filter(
            review_status=CrossSourceLinkCandidate.UNRESOLVED,
        ).values("reference_id").annotate(unresolved=Count("pk"))
    }
    thesis_groups = {}
    for thesis in source_theses_query.iterator(chunk_size=500):
        counts_for_thesis = reviewed_thesis_counts.get(thesis["id"], {})
        thesis["validated_links"] = counts_for_thesis.get("validated_links", 0)
        thesis["local_decisions"] = counts_for_thesis.get("local_decisions", 0)
        thesis["matched_local_decisions"] = matched_by_reference.get(thesis["id"], 0)
        thesis["unresolved_citations"] = unresolved_by_reference.get(thesis["id"], 0)
        normalized_thesis = " ".join(thesis["thesis"].casefold().split()) or thesis["title"]
        group = thesis_groups.setdefault(normalized_thesis, {
            "id": thesis["id"],
            "title": thesis["thesis"] or thesis["title"],
            "case_count": 0,
            "matched_local_decisions": 0,
            "unresolved_citations": 0,
            "source_references": [],
            "related_decisions": [],
            "approved": True,
        })
        group["case_count"] += 1
        group["matched_local_decisions"] += thesis["matched_local_decisions"]
        group["unresolved_citations"] += thesis["unresolved_citations"]
        group["approved"] = group["approved"] and thesis["approved"]
        if len(group["source_references"]) < 3:
            group["source_references"].append({
                "identifier": thesis["identifier"],
                "title": thesis["title"],
                "source_url": thesis["source_url"],
                "source_name": thesis["source_name"],
            })
        if len(source_theses) < 300:
            source_theses.append(thesis)
        for decision in thesis["related_decisions"]:
            key = str(decision.get("identifier", ""))
            if key and all(item["identifier"] != key for item in group["related_decisions"]):
                group["related_decisions"].append(decision)
    candidate_rows = list(
        candidate_scope.filter(
            local_decision__isnull=False,
            review_status__in=[CrossSourceLinkCandidate.PENDING, CrossSourceLinkCandidate.CONFIRMED],
        ).select_related("local_decision__process_dimension", "reference")
        .order_by("reference__title", "cited_identifier", "local_decision_id")[:100]
    )
    unresolved_rows = list(
        candidate_scope.filter(review_status=CrossSourceLinkCandidate.UNRESOLVED)
        .select_related("reference").order_by("reference__title", "cited_identifier")[:100]
    )
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
        "thesis_groups": sorted(
            thesis_groups.values(),
            key=lambda item: (-item["case_count"], -item["matched_local_decisions"], item["title"].casefold()),
        )[:8],
        "candidate_links": [
            {
                "local_source_id": row.local_decision.source_id,
                "local_process_number": row.local_decision.number_process,
                "reference_identifier": row.reference.identifier,
                "reference_title": row.reference.title,
                "reference_url": row.reference.source_url,
                "cited_identifier": row.cited_identifier,
                "relationship_type": row.relationship_type,
                "method": row.method,
                "method_version": row.method_version,
                "confidence": str(row.confidence) if row.confidence is not None else None,
                "review_status": row.review_status,
                "source_locator": row.source_locator,
                "explanation": row.explanation,
            }
            for row in candidate_rows
        ],
        "unresolved_candidates": [
            {
                "reference_identifier": row.reference.identifier,
                "reference_title": row.reference.title,
                "reference_url": row.reference.source_url,
                "cited_identifier": row.cited_identifier,
                "method": row.method,
                "method_version": row.method_version,
                "review_status": row.review_status,
                "source_locator": row.source_locator,
                "explanation": row.explanation,
            }
            for row in unresolved_rows
        ],
        "metadata": {
            "scope": {**selected, "date_field": "decision_date", "court": "TJDFT"},
            "source": "Corpus aprovado e avaliações revisadas; fontes citadas por registro.",
            "coverage": "Avaliações jurídicas validadas usam data de decisão informada na revisão. Sugestões por identificador abrangem as citações cadastradas nas fontes STJ e os registros TJDFT locais; não têm data de julgamento confiável e não recebem o filtro de período.",
            "limitations": [
                "Aderência e possível divergência refletem avaliações humanas validadas, não classificação automática.",
                "Vínculos pendentes, não revisados, incertos e fontes não aprovadas não entram nos indicadores.",
                "Distinguishing justificado é informado separadamente e não contado como aderência nem divergência.",
                "Indicadores são por vínculo decisão-precedente/doutrina, não por processo único nem por total de decisões do TJDFT.",
                "Uma possível divergência é sinal para revisão jurídica, não conclusão sobre erro ou descumprimento.",
                "Correspondência exata de identificador confirma somente a identidade do processo citado; não prova pertinência temática, aderência ou aplicabilidade do precedente.",
                "Citações sem CNJ completo ficam não resolvidas enquanto o texto das decisões TJDFT não estiver disponível; sugestões e citações não resolvidas não entram nos indicadores.",
            ],
            "candidate_link_coverage": {
                "matched": candidate_scope.filter(
                    local_decision__isnull=False,
                    review_status__in=[CrossSourceLinkCandidate.PENDING, CrossSourceLinkCandidate.CONFIRMED],
                ).count(),
                "unresolved": candidate_scope.filter(review_status=CrossSourceLinkCandidate.UNRESOLVED).count(),
                "date_filter_applied": False,
                "display_limit": 100,
            },
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
            "pangea_imports": list(
                PangeaImportRun.objects.order_by("-started_at").values(
                    "id", "started_at", "finished_at", "status", "scope", "catalog_version",
                    "source_total", "pages", "fetched", "created", "updated", "skipped", "rejected", "error",
                )[:5]
            ),
        },
    }
