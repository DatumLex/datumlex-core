import io
import json
from urllib.error import URLError
from xml.sax.saxutils import escape

from django.core.cache import cache
from django.db import DatabaseError
from django.db.models import F
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET, require_POST
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from src.routes.statistics import endpoint
from src.services import research, research_ai
from src.services.excel_report import workbook
from src.services.statistics_service import InvalidQuery


@endpoint
def panel(request):
    data = research.context(request.GET)
    return {**data, "summary": research.local_answer(data)}


@endpoint
def sources(request):
    params = request.GET.copy()

    def single(name, default):
        values = params.pop(name, [default])
        if len(values) != 1:
            raise InvalidQuery("Parâmetro repetido.")
        return values[0]

    category, term, page = single("category", ""), single("q", ""), single("page", "1")
    if (
        (category and category not in research.CATEGORIES)
        or len(term) > 120
        or not page.isascii()
        or not page.isdecimal()
        or len(page) > 6
        or int(page) < 1
    ):
        raise InvalidQuery("Categoria, página ou termo de busca inválido.")
    _, _, items = research.selection(params)
    if category:
        items = items.filter(category=category)
    if term:
        items = items.filter(title__icontains=term)
    rows = items.order_by(F("date").desc(nulls_last=True), "title", "pk")
    offset = (int(page) - 1) * 12
    return {
        "total": rows.count(),
        "items": [research.source_item(item) for item in rows[offset : offset + 12]],
    }


def error(message, status):
    return JsonResponse({"error": {"message": message}}, status=status)


@require_POST
def chat(request):
    try:
        if len(request.body) > 24000:
            return error("Mensagem muito longa.", 400)
        body = json.loads(request.body)
        if not isinstance(body, dict):
            raise ValueError
        question = body.get("question")
        previous = body.get("previous", [])
        if (
            not isinstance(question, str)
            or not 1 <= len(question.strip()) <= 1200
            or not isinstance(previous, list)
            or len(previous) > 4
            or any(not isinstance(q, str) or len(q) > 1200 for q in previous)
        ):
            raise ValueError
    except (ValueError, UnicodeError):
        return error("Envie uma pergunta de até 1.200 caracteres.", 400)
    try:
        data = research.context(research.question_scope(request.GET, question, previous), question, previous)
    except InvalidQuery as exc:
        return error(str(exc), 400)
    except DatabaseError:
        return error("O banco está indisponível para esta consulta.", 503)
    mode, notice = "local", ""
    paragraphs = None
    if research.ai_ready():
        if not cache.add(f"research:inflight:{request.user.pk}", True, timeout=40):
            return error("Uma resposta ainda está em andamento. Aguarde um instante.", 429)
        try:
            paragraphs = research_ai.generate(data, question, previous)
            mode = "openai"
        except (OSError, URLError, ValueError, KeyError, TypeError):
            notice = "A IA está indisponível. A resposta abaixo usa consulta direta ao acervo."
        finally:
            cache.delete(f"research:inflight:{request.user.pk}")
    paragraphs = paragraphs or research.local_answer(data, question, previous)
    cited = {ref for para in paragraphs for ref in para["refs"]}
    return JsonResponse(
        {
            "mode": mode,
            "notice": notice,
            "paragraphs": paragraphs,
            "sources": [s for s in data["sources"] if s["id"] in cited],
        }
    )


@require_GET
def export(request):
    params = request.GET.copy()
    formats = params.pop("format", [])
    if formats not in (["pdf"], ["xlsx"]):
        return error("Formato inválido.", 400)
    try:
        data = research.context(params)
        paragraphs = research.local_answer(data)
    except InvalidQuery as exc:
        return error(str(exc), 400)
    except DatabaseError:
        return error("O banco está indisponível para exportação.", 503)
    scope = data["scope"]
    scope_rows = [
        ["Tribunais", scope["court"]],
        ["Período", f"{scope['start']} a {scope['end']}"],
        ["Assuntos CNJ", ", ".join(map(str, scope["subject_codes"])) or "Todos"],
        ["Temas", ", ".join(data["topics"][k] for k in scope["topics"]) or "Todos"],
        ["Fontes", ", ".join(scope["sources"])],
        ["Resultados DataJud", ", ".join(scope["outcomes"])],
        ["Referências sem data", "Incluídas" if scope["undated"] else "Excluídas"],
    ]
    refs = [
        [s["id"], s["title"], s["origin"], str(s["date"] or "Sem data"), s["excerpt"], s["url"]]
        for s in data["sources"]
    ]
    summary = [[p["text"], ", ".join(p["refs"])] for p in paragraphs]
    if formats == ["xlsx"]:
        sheets = [
            ("Recorte", scope_rows),
            ("Síntese", [["Texto", "Referências"], *summary]),
            ("Fontes da síntese", [["ID", "Título", "Origem", "Data", "Trecho", "Link"], *refs]),
            (
                "Histórico",
                [
                    ["Ano", "Trimestre", "Grau", "Registros"],
                    *[
                        [r["time__year"], r["time__quarter"], r["degree"], r["count"]]
                        for r in data["history"]
                    ],
                ],
            ),
        ]
        response = HttpResponse(
            workbook(sheets), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        buffer = io.BytesIO()
        styles = getSampleStyleSheet()
        story = [Paragraph("DatumLex · Síntese da pesquisa", styles["Title"])]
        for line in (
            [" · ".join(row) for row in scope_rows]
            + [" ".join(row) for row in summary]
            + [" · ".join(row) for row in refs]
        ):
            story.extend([Paragraph(escape(line), styles["BodyText"]), Spacer(1, 5)])
        SimpleDocTemplate(buffer).build(story)
        response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="datumlex-pesquisa-{scope["start"]}-{scope["end"]}.{formats[0]}"'
    )
    return response
