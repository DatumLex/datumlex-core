"""Grounded conversational synthesis with Gemini over authorized DatumLex indicators and sources."""

import json
import math
import re
from collections import Counter
from datetime import timedelta
from hashlib import sha256
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from src.accounts.models import RequestLimit
from src.nlp.topics import folded
from src.services.corpus_catalog import CATEGORIES, scoped_items
from src.services.research import block, number, requested_categories, strip_source_ids

PII_PATTERNS = (
    (re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"), "[CPF omitido]"),
    (re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"), "[CNPJ omitido]"),
    (re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b"), "[CNJ omitido]"),
    (re.compile(r"\b\d{20}\b"), "[CNJ omitido]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[e-mail omitido]"),
)


class AnalysisUnavailable(ValueError):
    def __init__(self, message, *, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


class AnalysisRateLimited(AnalysisUnavailable):
    pass


def scrub_pii(text):
    cleaned = str(text or "")
    for pattern, token in PII_PATTERNS:
        cleaned = pattern.sub(token, cleaned)
    return " ".join(cleaned.split())


def cooldown_seconds():
    return max(0, int(getattr(settings, "RESEARCH_GEMINI_COOLDOWN_SECONDS", 8)))


def claim_request(user_id):
    wait = cooldown_seconds()
    if wait <= 0:
        return
    key = sha256(f"research-gemini:user:{user_id}".encode()).hexdigest()
    with transaction.atomic():
        now = timezone.now()
        limit, created = RequestLimit.objects.select_for_update().get_or_create(
            key=key, defaults={"count": 1, "expires_at": now + timedelta(seconds=wait)}
        )
        if not created:
            if limit.expires_at > now:
                remaining = max(1, math.ceil((limit.expires_at - now).total_seconds()))
                raise AnalysisRateLimited(
                    f"Aguarde {remaining}s antes da próxima solicitação ao Gemini.",
                    retry_after=remaining,
                )
            limit.expires_at = now + timedelta(seconds=wait)
            limit.count = 1
            limit.save(update_fields=["expires_at", "count"])


def findings(data):
    """Collect exact server-verified indicators and permission-checked sources for Gemini."""
    metrics = data["metrics"]
    available = {}
    if metrics["process_records"]:
        total = metrics["process_records"]
        distinct = metrics.get("distinct_process_numbers", total)
        available["volume"] = (
            {"quantity": total, "distinct_cnjs": distinct},
            block(
                f"O recorte contém {number(total)} documentos DataJud ({number(distinct)} CNJs distintos) por data de ajuizamento."
            ),
        )
    baseline = data["merit_baseline"]
    denominator = baseline["binary_denominator"]
    if denominator:
        granted, denied = baseline["granted"], baseline["denied"]
        grant_pct = round(baseline["grant_rate"] * 100, 1)
        denial_pct = round(baseline["denial_rate"] * 100, 1)
        available["outcomes"] = (
            {
                "granted": granted,
                "denied": denied,
                "denominator": denominator,
                "grant_rate_pct": grant_pct,
                "denial_rate_pct": denial_pct,
            },
            block(
                f"Entre {number(denominator)} documentos com resultado integral elegível antes do filtro de resultado, "
                f"{number(granted)} foram providos ({grant_pct}%) e {number(denied)} desprovidos ({denial_pct}%)."
            ),
        )
    years = Counter()
    for row in data["history"]:
        years[row["time__year"]] += row["count"]
    if years:
        year, count = min(years.items(), key=lambda item: (-item[1], item[0]))
        ties = sum(value == count for value in years.values())
        detail = " Outros anos atingiram o mesmo volume." if ties > 1 else ""
        available["history"] = (
            {"by_year": dict(sorted(years.items())), "peak_year": year, "peak_count": count},
            block(f"O ano {year} registrou {number(count)} documentos, o maior volume observado." + detail),
        )
    scope = data["scope"]
    allowed = scoped_items(scope, scope["undated"], use="gemini").filter(category__in=scope["sources"])
    if scope["topics"]:
        allowed = allowed.filter(topic_matches__topic__in=scope["topics"])
    counts = dict.fromkeys(CATEGORIES, 0)
    counts.update(dict(allowed.order_by().values_list("category").annotate(total=Count("id", distinct=True))))
    if any(counts.values()):
        available["catalog"] = (
            counts,
            block(
                f"O acervo do recorte contém {number(counts['jurisprudence'])} itens de jurisprudência, "
                f"{number(counts['precedent'])} precedentes qualificados e "
                f"{number(counts['doctrine'])} itens de doutrina autorizados para esta análise."
            ),
        )

    source_pks = [int(doc["id"][1:]) for doc in data["sources"] if re.fullmatch(r"F[0-9]+", doc["id"])]
    db_items = {
        f"F{obj.pk}": obj
        for obj in allowed.filter(pk__in=source_pks)
    }
    for doc in data["sources"]:
        obj = db_items.get(doc["id"])
        if obj is None or not doc.get("url"):
            continue
        perms = (obj.provenance or {}).get("permissions", {}) if isinstance(obj.provenance, dict) else {}
        gemini_meta = perms.get("gemini_metadata", perms.get("gemini", "denied")) == "allowed"
        gemini_full = perms.get("gemini_fulltext")
        # Respect explicit gemini_fulltext='denied' (never transmit full text or excerpt!)
        if gemini_full == "denied":
            allow_excerpt_for_ai = False
        elif gemini_full == "allowed":
            allow_excerpt_for_ai = perms.get("text") == "allowed"
        else:
            # Default for items without explicit gemini_fulltext key: allow authorized excerpt only when text='allowed' and gemini='allowed'
            allow_excerpt_for_ai = perms.get("text") == "allowed" and perms.get("gemini") == "allowed"

        if not gemini_meta and not allow_excerpt_for_ai:
            continue

        year_val = doc["date"].year if hasattr(doc.get("date"), "year") else (str(doc.get("date") or "")[:4] or None)
        ai_entry = {
            "id": doc["id"],
            "category": doc["kind"],
            "title": scrub_pii(doc.get("title", ""))[:280],
            "origin": scrub_pii(doc.get("origin") or doc.get("court") or "")[:120],
            "year": year_val,
            "authors": [scrub_pii(a)[:80] for a in (doc.get("authors") or [])[:5]],
        }
        if allow_excerpt_for_ai and doc.get("excerpt"):
            ai_entry["excerpt"] = scrub_pii(doc["excerpt"])[:1500]
            ai_entry["text_scope"] = "authorized_excerpt"
        else:
            ai_entry["text_scope"] = "metadata_only"

        source_text = f"Fonte · {doc['title']}." + (
            f" Trecho original: {doc['excerpt'][:700]}"
            if doc.get("excerpt")
            else " Referência bibliográfica; consulte a publicação original."
        )
        available[doc["id"]] = (ai_entry, block(source_text, [doc["id"]]))
    return available


def intent(question):
    query = folded(question)
    for label, stems in (
        ("history", ("evolu", "tendenc", "histor", "trimestr")),
        ("outcomes", ("mérito", "merito", "taxa", "proviment")),
        ("sources", ("doutrin", "jurisprud", "precedent", "fonte", "sumul", "tema", "ementa")),
    ):
        if any(stem in query for stem in stems):
            return label
    return "overview"


def generate(available, scope, question, previous=()):
    model = settings.RESEARCH_GEMINI_MODEL
    if not re.fullmatch(r"gemini-[a-z0-9.-]{1,70}", model):
        raise AnalysisUnavailable("Modelo Gemini inválido.")

    query_intent = intent(question)
    requested = requested_categories(question)
    active_sources = {
        key: values
        for key, (values, _) in available.items()
        if key.startswith("F")
    }
    if query_intent == "sources" and requested:
        matching_sources = {
            key: val for key, val in active_sources.items() if val.get("category") in requested
        }
        if matching_sources:
            active_sources = matching_sources

    metrics_payload = {
        key: values for key, (values, _) in available.items() if not key.startswith("F")
    }
    if not metrics_payload and not active_sources:
        raise AnalysisUnavailable("Não há fontes ou indicadores autorizados para esta consulta no recorte selecionado.")

    history_summary = [
        scrub_pii(strip_source_ids(turn))[:240]
        for turn in (previous or ())[-2:]
        if strip_source_ids(turn)
    ]
    payload = {
        "question": scrub_pii(question)[:1000],
        "intent": query_intent,
        "conversation_history": history_summary,
        "scope": {key: scope[key] for key in ("court", "start", "end", "subject_codes", "topics")},
        "metrics": metrics_payload,
        "sources": list(active_sources.values()),
    }

    allowed_ids = sorted(active_sources.keys())
    cited_schema = (
        {
            "type": "array",
            "maxItems": min(8, len(allowed_ids)),
            "items": {"type": "string", "enum": allowed_ids},
        }
        if allowed_ids
        else {"type": "array", "maxItems": 0, "items": {"type": "string"}}
    )
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["answer", "cited_source_ids", "limitations"],
        "properties": {
            "answer": {"type": "string", "minLength": 10},
            "cited_source_ids": cited_schema,
            "limitations": {"type": "string"},
        },
    }

    system_text = (
        "Você é o assistente jurídico do DatumLex. Responda diretamente à pergunta do usuário em português claro, "
        "fluido, objetivo e tecnicamente preciso, integrando exclusivamente os indicadores oficiais em 'metrics' "
        "e as fontes autorizadas em 'sources'.\n"
        "REGRAS OBRIGATÓRIAS:\n"
        "1. NUNCA altere, arredonde indevidamente ou invente números que não estejam em 'metrics'.\n"
        "2. NUNCA invente acórdãos, temas repetitivos, súmulas, autores, artigos ou números CNJ.\n"
        "3. Liste em 'cited_source_ids' apenas os IDs (formato F<número>) presentes em 'sources' que você efetivamente usou.\n"
        "4. Quando uma fonte tiver 'text_scope' = 'metadata_only', utilize apenas título, autoria, ano e origem, sem presumir conteúdo interno.\n"
        "5. Se não houver base suficiente no recorte para responder parte da pergunta, declare isso explicitamente.\n"
        "6. Em 'limitations', inclua uma frase curta sobre limitações metodológicas aplicáveis (ex.: cobertura parcial da amostra ou vínculo temático não equivale a aplicação judicial), sem repetir números já ditos."
    )

    request = Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"Content-Type": "application/json", "x-goog-api-key": settings.GEMINI_API_KEY},
        data=json.dumps({
            "systemInstruction": {"parts": [{"text": system_text}]},
            "contents": [{"parts": [{"text": json.dumps(payload, ensure_ascii=False)}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
                "maxOutputTokens": 1024,
                "thinkingConfig": {"thinkingLevel": "minimal"},
            },
        }).encode("utf-8"),
    )
    try:
        with urlopen(request, timeout=25) as response:
            result = json.loads(response.read(65536))
        candidate, = result["candidates"]
        if candidate["finishReason"] != "STOP":
            raise ValueError("incomplete_generation")
        output = json.loads("".join(
            item["text"] for item in candidate["content"]["parts"] if not item.get("thought")
        ))
        if not isinstance(output, dict) or set(output) != {"answer", "cited_source_ids", "limitations"}:
            raise ValueError("invalid_schema_keys")
        answer_text = output["answer"].strip() if isinstance(output["answer"], str) else ""
        limitations_text = output["limitations"].strip() if isinstance(output["limitations"], str) else ""
        raw_cited = output["cited_source_ids"]
        if not answer_text or not isinstance(raw_cited, list) or any(not isinstance(k, str) for k in raw_cited):
            raise ValueError("invalid_answer_or_citations")
    except HTTPError as error:
        if error.code == 429:
            raise AnalysisRateLimited("O Gemini atingiu o limite de requisições da API.") from None
        raise AnalysisUnavailable("O Gemini está temporariamente indisponível.") from None
    except (URLError, OSError, ValueError, KeyError, TypeError):
        raise AnalysisUnavailable("O Gemini não retornou uma resposta estruturada verificável.") from None

    # Strict server-side validation: discard any citation ID not in the authorized sources sent to Gemini
    allowed_set = set(allowed_ids)
    verified_cited = list(dict.fromkeys(cid for cid in raw_cited if cid in allowed_set))

    # Split narrative into clean paragraphs and attach verified cited_source_ids to the final narrative paragraph
    parts = [p.strip() for p in re.split(r"\n{2,}", answer_text) if p.strip()]
    if not parts:
        parts = [answer_text]
    paragraphs = []
    for idx, text_part in enumerate(parts):
        # Also detect any inline F<id> references in this paragraph that are in verified_cited
        inline_refs = [f"F{m}" for m in re.findall(r"\bF([1-9][0-9]{0,17})\b", text_part) if f"F{m}" in allowed_set]
        refs = list(dict.fromkeys(inline_refs))
        if idx == len(parts) - 1:
            refs = list(dict.fromkeys([*refs, *verified_cited]))
        paragraphs.append(block(text_part, refs))
    if limitations_text:
        paragraphs.append(block(limitations_text, []))
    return paragraphs
