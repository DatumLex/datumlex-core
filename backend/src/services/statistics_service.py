from datetime import date

from django.db.models import Count, Max, Min

from src.db.models import ExtractionRun, FactProcess
from src.services.outcomes import summarize


class InvalidQuery(ValueError):
    pass


def filtered_processes(params):
    allowed = {"court", "subject", "start", "end", "outcome", "page", "page_size"}
    if set(params) - allowed:
        raise InvalidQuery("Unsupported query parameter")
    if any(len(params.getlist(key)) > 1 for key in params):
        raise InvalidQuery("Repeated query parameters are not supported")
    if params.get("court", "TJDFT") != "TJDFT":
        raise InvalidQuery("Only TJDFT is available")
    if params.get("outcome", "all") not in {"all", "granted", "denied"}:
        raise InvalidQuery("outcome must be all, granted or denied")
    try:
        start = date.fromisoformat(params.get("start", "2023-01-01"))
        end = date.fromisoformat(params.get("end", date.today().isoformat()))
        if start < date(2023, 1, 1) or start > end or end > date.today():
            raise ValueError
        subject = int(params["subject"]) if params.get("subject") else None
        if subject is not None and subject < 1:
            raise ValueError
    except ValueError:
        raise InvalidQuery("Invalid date range (2023..today) or subject code") from None
    query = FactProcess.objects.filter(court="TJDFT", time__date__range=[start, end])
    if subject:
        query = query.filter(subjects__code=subject)
    # Distinct document grain protects all aggregates from the multi-subject bridge.
    return query.distinct(), {
        "court": "TJDFT",
        "subject": subject,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "outcome": params.get("outcome", "all"),
        "period_field": "dataAjuizamento",
        "grain": "DataJud document (source_id), not unique appeal or unique CNJ process",
    }


def metadata(query, scope):
    latest = ExtractionRun.objects.order_by("-id").first()
    dates = query.aggregate(first=Min("time__date"), last=Max("time__date"), refreshed=Max("collected_at"))
    return {
        "source": "DataJud / CNJ",
        "scope": scope,
        "available_period": {"start": dates["first"], "end": dates["last"]},
        "last_record_refresh": dates["refreshed"],
        "latest_run": None
        if latest is None
        else {
            "id": latest.pk,
            "status": latest.status,
            "scope": latest.scope,
            "fetched": latest.fetched,
            "rejected": latest.rejected,
            "stale": latest.stale,
            "source_total": latest.source_total,
            "source_total_relation": latest.source_total_relation,
            "finished_at": latest.finished_at,
        },
        "coverage": "Local loaded records only; consult run scopes, limits and rejections. Full coverage is not asserted.",
        "merit_status": "document_proxy",
        "merit_reason": "Latest dated mapped TPU outcome per document in G2/TR; timestamp ties use highest local movement ID. Partial/non-admitted outcomes remain outside binary denominator. Filing-date filter, not judgment-date filter.",
    }


def metrics(query):
    return {
        "process_records": query.count(),
        "distinct_process_numbers": query.values("number_process").distinct().count(),
        "analyzed_appeals": None,
        **summarize(query),
    }


def instance_series(query):
    return list(
        query.values("time__year", "time__quarter", "degree")
        .annotate(count=Count("pk", distinct=True))
        .order_by("time__year", "time__quarter", "degree")
    )
