from django.db import DatabaseError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET

from src.services.pangea_report import report_references
from src.services.pdf_report import build_report
from src.services.report_cases import case_summaries
from src.services.report_context import report_context
from src.services.report_transaction import report_transaction
from src.services.statistics_service import (
    InvalidQuery,
    filtered_processes,
    instance_series,
    metadata,
    metrics,
)


@require_GET
def report(request):
    try:
        with report_transaction():
            query, selected = filtered_processes(request.GET)
            content = build_report(
                selected,
                metrics(query),
                metadata(query, selected),
                instance_series(query),
                report_references(selected),
                case_summaries(query),
                report_context(query, selected, request.user),
            )
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="datumlex-{selected["start"]}-{selected["end"]}.pdf"'
        )
        response["Cache-Control"] = "no-store"
        return response
    except InvalidQuery as error:
        return JsonResponse({"error": {"message": str(error)}}, status=400)
    except DatabaseError:
        return JsonResponse(
            {"error": {"message": "Não foi possível consultar os dados para o relatório."}}, status=503
        )
