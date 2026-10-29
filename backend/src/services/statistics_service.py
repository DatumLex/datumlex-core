from datetime import date

from django.db.models import Count, Exists, F, Max, Min, OuterRef

from src.db.models import ExtractionRun, FactProcess, FactProcessSubject
from src.services.outcomes import summarize
from src.services.period import HISTORY_START, today
from src.db.court_catalog import ACTIVE_COURTS as COURTS


class InvalidQuery(ValueError):
    pass


def filtered_processes(params):
    allowed = {"court", "subject", "start", "end", "outcome", "page", "page_size"}
    if set(params) - allowed:
        raise InvalidQuery("Unsupported query parameter")
    if any(len(params.getlist(key)) > 1 for key in params):
        raise InvalidQuery("Repeated query parameters are not supported")
    court = params.get("court", "TJDFT")
    courts = court.split(",")
    if not courts or any(item not in COURTS for item in courts) or len(set(courts)) != len(courts):
        raise InvalidQuery("Unsupported or repeated DataJud court")
    if params.get("outcome", "all") not in {"all", "granted", "denied"}:
        raise InvalidQuery("outcome must be all, granted or denied")
    try:
        start = date.fromisoformat(params.get("start", HISTORY_START.isoformat()))
        end = date.fromisoformat(params.get("end", today().isoformat()))
        if start < HISTORY_START or start > end or end > today():
            raise ValueError
        subject = int(params["subject"]) if params.get("subject") else None
        if subject is not None and subject < 1:
            raise ValueError
    except ValueError:
        raise InvalidQuery("Invalid date range (2016..today) or subject code") from None
    query = FactProcess.objects.filter(court__in=courts, time__date__range=[start, end])
    if subject:
        query = query.filter(
            Exists(FactProcessSubject.objects.filter(process_id=OuterRef("pk"), subject__code=subject))
        )
    # EXISTS keeps one row per document without DISTINCT over large JSON payloads.
    return query, {
        "court": court,
        "subject": subject,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "outcome": params.get("outcome", "all"),
        "period_field": "dataAjuizamento",
        "grain": "DataJud document (source_id), not unique appeal or unique CNJ process",
    }


def metadata(query, scope):
    latest = ExtractionRun.objects.filter(scope__court__in=scope["court"].split(",")).order_by("-id").first()
    dates = query.aggregate(first=Min("time__date"), last=Max("time__date"), refreshed=Max("collected_at"))
    return {
        "source": "DataJud / CNJ",
        "outcome_supported_courts": ['TJDFT', 'STJ'],
        "unvalidated_outcome_courts": [c for c in scope['court'].split(',') if c not in ('TJDFT', 'STJ')],
        "source_url": "https://api-publica.datajud.cnj.jus.br/",
        "loaded_records": query.count(),
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
        "uncertainty": "DataJud metadata is not a curated precedent or doctrine corpus. No legal alignment is inferred from shared process numbers or movement labels.",
        "merit_status": "document_proxy",
        "merit_reason": "Latest dated mapped TPU outcome per DataJud document (G2/TR for TJDFT; SUP for STJ); timestamp ties use highest local movement ID. Partial, partial-knowledge and non-admitted outcomes remain outside the binary denominator. Filing-date filter, not judgment-date filter; not a count of individual appeals.",
    }


def metadata_by_court(query, scope):
    """Bulk source-card metadata, avoiding one HTTP request per selected tribunal."""
    selected = scope['court'].split(',')
    counts = {r['court']: r for r in query.order_by().values('court').annotate(
        total=Count('pk'), first=Min('time__date'), last=Max('time__date'))}
    latest = {}
    for run in ExtractionRun.objects.filter(scope__court__in=selected).order_by('-pk').values(
            'id', 'scope', 'status', 'fetched', 'rejected'):
        latest.setdefault(run['scope']['court'], {k: v for k, v in run.items() if k != 'scope'})
    return {court: {'source': 'DataJud / CNJ', 'loaded_records': counts.get(court, {}).get('total', 0),
        'available_period': {'start': counts.get(court, {}).get('first'), 'end': counts.get(court, {}).get('last')},
        'latest_run': latest.get(court), 'coverage': 'Somente documentos carregados; cadastro do tribunal não comprova cobertura.'}
        for court in selected}


def metrics(query):
    totals = query.aggregate(
        process_records=Count("pk", distinct=True),
        distinct_process_numbers=Count("process_dimension_id", distinct=True),
    )
    return {
        **totals,
        "analyzed_appeals": None,
        **summarize(query),
    }


def instance_series(query):
    return list(
        query.annotate(degree=F("degree_dimension__code"))
        .values("time__year", "time__quarter", "degree")
        .annotate(count=Count("pk", distinct=True))
        .order_by("time__year", "time__quarter", "degree")
    )
