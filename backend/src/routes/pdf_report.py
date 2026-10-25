from django.db import DatabaseError, connection, transaction
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET

from src.services.pdf_report import build_report
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
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            query, selected = filtered_processes(request.GET)
            content = build_report(
                selected, metrics(query), metadata(query, selected), instance_series(query)
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
