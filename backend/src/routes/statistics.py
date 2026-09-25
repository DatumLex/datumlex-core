from functools import wraps

from django.db import DatabaseError, connection
from django.db.models import Prefetch
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from src.db.models import DimSubject, FactProcess, ProcessMovement
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
