"""Gemini ranks verified findings from the active research scope."""

import json
import re
from collections import Counter
from datetime import timedelta
from hashlib import sha256
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from src.accounts.models import RequestLimit
from src.nlp.topics import folded
from src.services.research import block, number


class AnalysisUnavailable(ValueError):
    pass


class AnalysisRateLimited(AnalysisUnavailable):
    pass


def claim_request(user_id):
    key = sha256(f"research-gemini:user:{user_id}".encode()).hexdigest()
    with transaction.atomic():
        now = timezone.now()
        limit, created = RequestLimit.objects.select_for_update().get_or_create(
            key=key, defaults={"count": 1, "expires_at": now + timedelta(minutes=1)}
        )
        if not created:
            if limit.expires_at > now:
                raise AnalysisRateLimited("Aguarde um minuto entre solicitações ao Gemini.")
            limit.expires_at = now + timedelta(minutes=1)
            limit.count = 1
            limit.save(update_fields=["expires_at", "count"])


def findings(data):
    metrics = data["metrics"]
    available = {}
    if metrics["process_records"]:
        total = metrics["process_records"]
        available["volume"] = (
            {"quantity": total},
            block(f"O recorte contém {number(total)} registros DataJud por data de ajuizamento."),
        )
    baseline = data["merit_baseline"]
    denominator = baseline["binary_denominator"]
    if denominator:
        granted, denied = baseline["granted"], baseline["denied"]
        available["outcomes"] = (
            {"granted": granted, "denied": denied, "denominator": denominator},
            block(
                f"Entre {number(denominator)} documentos com resultado integral elegível antes do filtro de resultado, "
                f"{number(granted)} foram classificados como providos e {number(denied)} como desprovidos."
            ),
        )
    years = Counter()
    for row in data["history"]:
        years[row["time__year"]] += row["count"]
    if years:
        year, count = min(years.items(), key=lambda item: (-item[1], item[0]))
        ties = sum(value == count for value in years.values())
        detail = (
            " Outros anos atingiram o mesmo volume." if ties > 1 else ""
        )
        available["history"] = (
            {"by_year": dict(sorted(years.items()))},
            block(f"O ano {year} registrou {number(count)} documentos, o maior volume observado." + detail),
        )
    if any(data["counts"].values()):
        counts = data["counts"]
        available["catalog"] = (
            counts,
            block(
                f"O acervo do recorte contém {number(counts['jurisprudence'])} itens de jurisprudência, "
                f"{number(counts['precedent'])} referências a precedentes e "
                f"{number(counts['doctrine'])} itens de doutrina. O total pode incluir itens pendentes."
            ),
        )
    for doc in data["sources"]:
        # Only approved references with a resolvable link enter the model's selection pool.
        if doc.get("review_status") == "approved" and doc["url"]:
            available[doc["id"]] = (
                {"category": doc["kind"]},
                block("Fonte revisada recuperada no recorte. Consulte o trecho e a publicação original.", [doc["id"]]),
            )
    return available


def intent(question):
    query = folded(question)
    for label, stems in (
        ("history", ("evolu", "tendenc", "histor", "trimestr")),
        ("outcomes", ("mérito", "merito", "taxa", "proviment")),
        ("sources", ("doutrin", "jurisprud", "precedent", "fonte")),
    ):
        if any(stem in query for stem in stems):
            return label
    return "overview"


def generate(available, scope, question):
    model = settings.RESEARCH_GEMINI_MODEL
    if not re.fullmatch(r"gemini-[a-z0-9.-]{1,70}", model):
        raise AnalysisUnavailable("Modelo Gemini inválido.")
    payload = {
        "intent": intent(question),
        "scope": {key: scope[key] for key in ("court", "start", "end", "subject_codes", "topics")},
        "findings": {key: values for key, (values, _) in available.items()},
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["findings"],
        "properties": {
            "findings": {
                "type": "array",
                "minItems": 1,
                "maxItems": min(5, len(available)),
                "items": {"type": "string", "enum": list(available)},
            }
        },
    }
    request = Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"Content-Type": "application/json", "x-goog-api-key": settings.GEMINI_API_KEY},
        data=json.dumps({
            "systemInstruction": {"parts": [{"text": (
                "Selecione e ordene até cinco achados relevantes à intenção da consulta. "
                "Aponte apenas as chaves permitidas. Não gere texto livre, números, nomes ou URLs."
            )}]},
            "contents": [{"parts": [{"text": json.dumps(payload)}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
                "maxOutputTokens": 512,
                "thinkingConfig": {"thinkingLevel": "minimal"},
            },
        }).encode(),
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read(16000))
        candidate, = result["candidates"]
        if candidate["finishReason"] != "STOP":
            raise ValueError
        output = json.loads("".join(
            item["text"] for item in candidate["content"]["parts"] if not item.get("thought")
        ))
        if not isinstance(output, dict) or set(output) != {"findings"}:
            raise ValueError
        selected = output["findings"]
        if (
            not isinstance(selected, list)
            or not 1 <= len(selected) <= 5
            or any(not isinstance(key, str) or key not in available for key in selected)
            or len(set(selected)) != len(selected)
        ):
            raise ValueError
    except HTTPError as error:
        if error.code == 429:
            raise AnalysisRateLimited("O Gemini atingiu o limite de requisições.") from None
        raise AnalysisUnavailable("O Gemini está indisponível.") from None
    except (URLError, OSError, ValueError, KeyError, TypeError):
        raise AnalysisUnavailable("O Gemini não retornou uma seleção verificável.") from None
    return [available[key][1] for key in selected] + [
        block("Achados selecionados pelo Gemini. Os números são calculados pelo DatumLex e descrevem a amostra.")
    ]
