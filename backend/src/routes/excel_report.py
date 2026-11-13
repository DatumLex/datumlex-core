from django.db import DatabaseError, connection, transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from src.services.excel_report import document_rows, workbook
from src.services.statistics_service import InvalidQuery, filtered_processes, instance_series, metrics


@require_GET
def report(request):
    try:
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            query, scope = filtered_processes(request.GET)
            if scope["outcome"] != "all":
                raise InvalidQuery("A exportação inclui todos os resultados; use outcome=all.")
            totals = metrics(query)
            summary = [["Indicador", "Valor"]]
            for key, value in totals.items():
                if isinstance(value, dict):
                    summary.extend([f"{key}.{k}", v] for k, v in value.items())
                else:
                    summary.append([key, value])
            context = [["Campo", "Valor"], *[[k, v] for k, v in scope.items()],
                ["Exportado em (UTC)", timezone.now().isoformat()],
                ["Fonte", "DataJud / CNJ"],
                ["Cobertura", "Somente documentos carregados na base local; cobertura parcial."],
                ["Unidade", "Uma linha por documento DataJud; não representa recurso individual ou processo CNJ único."],
                ["Resultados", "Proxy por documento, conforme classificação do painel; taxas entre 0 e 1. O período usa data de ajuizamento."],
                ["Limites", "Textos limitados a 32767 caracteres por célula (limite do Excel)."]]
            series = [["Ano", "Trimestre", "Instância", "Documentos"], *[[r["time__year"], r["time__quarter"], r["degree"], r["count"]] for r in instance_series(query)]]
            content = workbook([("Documentos", document_rows(query)), ("Indicadores", summary), ("Trimestres", series), ("Contexto", context)])
        response = HttpResponse(content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f'attachment; filename="datumlex-{scope["start"]}-{scope["end"]}.xlsx"'
        response["Cache-Control"] = "no-store"
        return response
    except (InvalidQuery, ValueError) as error:
        return JsonResponse({"error": {"message": str(error)}}, status=400)
    except DatabaseError:
        return JsonResponse({"error": {"message": "Não foi possível consultar os dados para a planilha."}}, status=503)
