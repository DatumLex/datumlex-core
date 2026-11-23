import io
import json
from itertools import chain
from xml.sax.saxutils import escape

from django.conf import settings
from django.db import DatabaseError
from django.db.models import F, Q
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
def coverage(request):
    _, scope, _, _ = research.selection(request.GET)
    return {"coverage": research.coverage(scope)}


def process_rows(query):
    return query.order_by("time__date", "pk").values_list(
        "pk", "process_dimension__number_process", "court", "time__date", "degree_dimension__code",
        "result__name", "organization__name", "process_class__name",
    )


@endpoint
def processes(request):
    params = request.GET.copy()
    page = params.pop("page", ["1"])
    if len(page) != 1 or not page[0].isascii() or not page[0].isdigit() or not 1 <= len(page[0]) <= 5:
        raise InvalidQuery("Página inválida.")
    page = int(page[0])
    if page < 1:
        raise InvalidQuery("Página inválida.")
    query, _, _, _ = research.selection(params)
    offset = (page - 1) * 12
    rows = process_rows(query)[offset:offset + 12]
    return {"total": query.count(), "items": [
        {"id": pk, "number": number, "court": court, "filing": filing, "degree": degree,
         "outcome": "outside_appellate_degree" if outcome == "outside_degree" else outcome,
         "organization": org, "class_name": cls}
        for pk, number, court, filing, degree, outcome, org, cls in rows
    ]}


@endpoint
def sources(request):
    params = request.GET.copy()

    def single(name, default):
        values = params.pop(name, [default])
        if len(values) != 1:
            raise InvalidQuery("Parâmetro repetido.")
        return values[0]

    category, term, page = single("category", ""), single("q", "").strip(), single("page", "1")
    all_dates = single("all_dates", "false")
    if (
        (category and category not in research.CATEGORIES)
        or len(term) > 120
        or all_dates not in ("true", "false")
        or (all_dates == "true" and (category != "precedent" or not term))
        or not page.isascii()
        or not page.isdecimal()
        or len(page) > 6
        or int(page) < 1
    ):
        raise InvalidQuery("Categoria, página ou termo de busca inválido.")
    _, _, items, _ = research.selection(params, precedent_all_dates=all_dates == "true")
    if category:
        items = items.filter(category=category)
    if term:
        items = items.filter(Q(title__icontains=term) | Q(provenance__metadata__id__iexact=term))
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
        use_gemini = body.get("use_gemini", False)
        if (
            not isinstance(question, str)
            or not 1 <= len(question.strip()) <= 1200
            or not isinstance(use_gemini, bool)
            or not isinstance(previous, list)
            or len(previous) > 4
            or any(not isinstance(q, str) or len(q) > 1200 for q in previous)
        ):
            raise ValueError
    except (ValueError, UnicodeError):
        return error("Envie uma pergunta de até 1.200 caracteres.", 400)
    try:
        params = research.question_scope(request.GET, question, previous)
        data = research.context(params, question, previous)
    except InvalidQuery as exc:
        return error(str(exc), 400)
    except DatabaseError:
        return error("O banco está indisponível para esta consulta.", 503)
    mode, notice, retry_after = "local", "", 0
    paragraphs = None
    if use_gemini and research.ai_ready():
        available = research_ai.findings(data)
        if not available:
            notice = "O recorte não contém dados suficientes para análise com Gemini."
        else:
            try:
                research_ai.claim_request(request.user.pk)
                paragraphs = research_ai.generate(available, data["scope"], question, previous=previous)
                if research_ai.findings(data) != available:
                    raise research_ai.AnalysisUnavailable("As permissões das fontes mudaram durante a consulta.")
                mode = "gemini"
            except research_ai.AnalysisUnavailable as exc:
                paragraphs = None
                retry_after = getattr(exc, "retry_after", 0)
                notice = f"{exc} Veja a consulta direta ao acervo abaixo."
                try:
                    data = research.context(params, question, previous)
                except DatabaseError:
                    return error("O banco está indisponível para esta consulta.", 503)
            except DatabaseError:
                return error("O banco está indisponível para esta consulta.", 503)
    elif use_gemini:
        notice = "Gemini não está configurado. Veja a consulta direta ao acervo abaixo."
    paragraphs = paragraphs or research.local_answer(data, question, previous)
    cited = {ref for para in paragraphs for ref in para["refs"]}
    intent_id = research_ai.intent(question)
    nlp_summary = {
        **(data.get("nlp") or {}),
        "intent": intent_id,
        "intent_label": research.INTENT_LABELS.get(intent_id, research.INTENT_LABELS["overview"]),
    }
    return JsonResponse(
        {
            "mode": mode,
            "notice": notice,
            "retry_after": retry_after,
            "cooldown_seconds": research_ai.cooldown_seconds(),
            "inherited_context": data.get("inherited_context") or {},
            "paragraphs": paragraphs,
            "sources": [s for s in data["sources"] if s["id"] in cited],
            "nlp": nlp_summary,
        }
    )


SOURCE_LABELS = {
    "datajud": "DataJud", "jurisprudence": "Jurisprudência", "precedent": "Precedentes", "doctrine": "Doutrina",
}
OUTCOME_LABELS = {
    "granted": "Provido", "denied": "Desprovido", "partial": "Parcial",
    "not_admitted": "Não admitido", "partial_knowledge": "Conhecido em parte",
    "ambiguous": "Ambíguo", "unknown": "Sem resultado", "outside_appellate_degree": "Fora do grau recursal",
    "outside_degree": "Fora do grau recursal",
}


def export_scope(scope):
    return [
        ["Tribunais", scope["court"]],
        ["Período", f"{scope['start']} a {scope['end']}"],
        ["Datas", "DataJud por ajuizamento. Acervo por julgamento ou publicação."],
        ["Assuntos CNJ selecionados", ", ".join(map(str, scope["selected_subject_codes"])) or "Todos"],
        ["Assuntos CNJ", ", ".join(map(str, scope["subject_codes"])) or "Todos"],
        ["Regra TPU", "Descendentes incluídos. União dos ramos sem duplicar o documento."],
        ["Graus DataJud", ", ".join(scope["degree"]) or "Todos"],
        ["Temas do acervo e ementas", ", ".join(research.TOPIC_LABELS[k] for k in scope["topics"]) or "Todos"],
        ["Fontes", ", ".join(SOURCE_LABELS[k] for k in scope["sources"])],
        ["Resultados DataJud", ", ".join(OUTCOME_LABELS[k] for k in scope["outcomes"])],
        ["Amostra DataJud", scope["cohort"] or "Base carregada"],
        ["Cobertura", "Parcial. Descreve o lote disponível."],
        ["Referências sem data", "Incluídas" if scope["undated"] else "Excluídas"],
        ["Número CNJ exato", scope["cnj"] or "Todos"],
    ]


@require_GET
def export(request):
    params = request.GET.copy()
    formats = params.pop("format", [])
    if formats not in (["pdf"], ["xlsx"]):
        return error("Formato inválido.", 400)
    content = params.pop("content", ["summary"])
    if content not in (["summary"], ["records"]) or (content == ["records"] and formats != ["xlsx"]):
        return error("Conteúdo inválido para este formato.", 400)
    try:
        if content == ["records"]:
            query, scope, _, _ = research.selection(params)
            header = ["Número CNJ", "Tribunal", "Classe", "Grau", "Órgão", "Ajuizamento", "Resultado"]
            rows = (
                [number, court, cls, degree, org, str(day), OUTCOME_LABELS.get(outcome, outcome)]
                for _, number, court, day, degree, outcome, org, cls in process_rows(query).iterator()
            )
            try:
                book = workbook([("Processos", chain([header], rows)), ("Recorte", export_scope(scope))])
            except ValueError as exc:
                return error(str(exc), 400)
            response = HttpResponse(
                book, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = 'attachment; filename="datumlex-registros-datajud.xlsx"'
            return response
        data = research.context(params)
        paragraphs = research.local_answer(data)
    except InvalidQuery as exc:
        return error(str(exc), 400)
    except DatabaseError:
        return error("O banco está indisponível para exportação.", 503)
    scope = data["scope"]
    scope_rows = export_scope(scope)
    baseline = data["merit_baseline"]
    metrics_rows = [
        ["Registros DataJud", str(data["metrics"]["process_records"])],
        ["Números CNJ distintos", str(data["metrics"]["distinct_process_numbers"])],
        ["Resultados integrais antes do filtro de resultado", str(baseline["binary_denominator"])],
        ["Providos na base elegível", str(baseline["granted"])],
        ["Desprovidos na base elegível", str(baseline["denied"])],
        *[[f"Excluídos da base binária ({OUTCOME_LABELS[k]})", str(n)] for k, n in baseline["excluded"].items() if n],
        ["Interpretação", "A proporção descreve os documentos elegíveis da amostra e não estima a chance de êxito judicial."],
        ["Jurisprudência no índice do recorte", str(data["counts"]["jurisprudence"])],
        ["Precedentes no índice do recorte", str(data["counts"]["precedent"])],
        ["Doutrina no índice do recorte", str(data["counts"]["doctrine"])],
    ]
    rate = data["merit_baseline"]["grant_rate"]
    metrics_rows.append(["Taxa de provimento antes do filtro de resultado",
                         f"{rate:.1%}".replace(".", ",") if rate is not None else "Indisponível"])
    refs = [
        [s["id"], s["title"], s["origin"], str(s["date"] or "Sem data"), s["excerpt"], s["url"], s.get("review_status", "pending")]
        for s in data["sources"]
    ]
    summary = [[p["text"], ", ".join(p["refs"])] for p in paragraphs]
    if formats == ["xlsx"]:
        sheets = [
            ("Recorte", scope_rows),
            ("Síntese", [["Texto", "Referências"], *summary]),
            ("Fontes da síntese", [["ID", "Título", "Origem", "Data", "Trecho", "Link", "Revisão"], *refs]),
            ("Indicadores", [["Indicador", "Valor"], *metrics_rows]),
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
        if settings.SYNTHETIC_PREVIEW:
            story.append(Paragraph("Dados sintéticos. Os indicadores não representam estatísticas reais.", styles["Heading2"]))
        for row in scope_rows + metrics_rows + summary:
            story.extend([Paragraph(escape(" · ".join(row)), styles["BodyText"]), Spacer(1, 5)])
        for ref_id, title, origin, day, excerpt, url, review in refs:
            label = escape(f"{ref_id} · {title} · {origin} · {day} · revisão: {review}")
            if url:
                link = escape(url, {'"': "&quot;", "'": "&#39;"})
                label += f' · <link href="{link}" color="blue">Abrir fonte original</link>'
            story.extend([Paragraph(label, styles["BodyText"]),
                          Paragraph(escape(excerpt), styles["BodyText"]), Spacer(1, 7)])
        SimpleDocTemplate(buffer).build(story)
        response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="datumlex-pesquisa-{scope["start"]}-{scope["end"]}.{formats[0]}"'
    )
    return response
