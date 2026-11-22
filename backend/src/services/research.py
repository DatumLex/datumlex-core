"""Research context shared by the panel, conversational search, exports and the optional model."""

import re
from collections import Counter

from django.conf import settings
from django.db.models import Case, Count, Exists, F, IntegerField, Max, Min, OuterRef, Value, When

from src.db.civil_subjects import branch_codes
from src.db.court_catalog import ACTIVE_COURTS
from src.db.models import ExtractionRun, FactProcessSubject, LegalCorpusTopicMatch
from src.db.sampling_models import CivilSampleMember, CivilSamplingCohort
from src.etl.cross_source_matching import normalize_cnj_identifier
from src.nlp.topics import TOPICS, classify, folded
from src.services.analytical_context import OUTCOMES
from src.services.corpus_catalog import CATEGORIES, safe_url, scoped_items
from src.services.corpus_publication import with_public_excerpt
from src.services.precedent_usage import summarize as usage_summary
from src.services.source_metadata import public_source_metadata
from src.services.statistics_service import InvalidQuery, filtered_processes, instance_series, metrics
from src.services.outcomes import summarize


TOPIC_LABELS = {key: label for key, label, _ in TOPICS}
SOURCES = ("datajud", *CATEGORIES)
DEGREES = ("G1", "G2", "JE", "TR", "SUP")
TYPES = {"jurisprudence": "Decisão", "precedent": "Precedente", "doctrine": "Doutrina"}
RELATIONS = {
    "applied": "aplicação explícita",
    "not_applied": "afastamento explícito",
    "mentioned": "menção",
    "ambiguous": "vínculo ambíguo",
}
SOURCE_ID = re.compile(r"\bF([1-9][0-9]{0,17})\b", re.I)
STOP = set(
    "sobre esses essas deste desta quais algum alguma doutrina jurisprudencia jurisprudência precedente precedentes dados fonte fontes pesquisa trecho trechos decisao decisão decisões quero favor explique mostre tema período periodo".split()
)


def follows_up(question):
    return bool(
        re.search(r"^e\s|\b(isso|nesse|nessa|desse|dessa|mesmo tema|sobre ele|sobre ela)\b", folded(question))
    )


def question_scope(params, question, previous):
    courts = set(params.get("court", "TJDFT").split(","))
    named = set(re.findall(r"\b[A-Z]{2,8}\b", question.upper())) & set(ACTIVE_COURTS)
    if not named and previous and follows_up(question):
        named = set(re.findall(r"\b[A-Z]{2,8}\b", previous[-1].upper())) & set(ACTIVE_COURTS)
    if named - courts:
        raise InvalidQuery("O tribunal mencionado está fora deste recorte. Ajuste os filtros da pesquisa.")
    filtered = params.copy()
    if named:
        filtered["court"] = ",".join(sorted(named))
    return filtered


def options(params, name, choices, default=()):
    raw = params.get(name)
    values = list(default) if raw is None else list(dict.fromkeys(filter(None, raw.split(","))))
    if any(v not in choices for v in values):
        raise InvalidQuery(f"Seleção inválida: {name}.")
    return sorted(values)


def selection(params, *, precedent_all_dates=False):
    allowed = {"court", "start", "end", "subject", "topics", "sources", "outcomes", "degree", "undated", "cnj"}
    if set(params) - allowed or any(len(params.getlist(k)) != 1 for k in params):
        raise InvalidQuery("Filtro de pesquisa desconhecido ou repetido.")
    process_filters = params.copy()
    for k in set(params) - {"court", "start", "end"}:
        process_filters.pop(k)
    query, scope = filtered_processes(process_filters)
    subjects = list(dict.fromkeys(filter(None, params.get("subject", "").split(","))))
    if len(subjects) > 50 or any(not re.fullmatch(r"[1-9][0-9]{0,8}", code) for code in subjects):
        raise InvalidQuery("Assunto CNJ inválido.")
    selected_subjects = sorted(map(int, subjects))
    subjects = sorted(set().union(*(branch_codes(code) for code in selected_subjects)))
    if subjects:
        query = query.filter(
            Exists(FactProcessSubject.objects.filter(process_id=OuterRef("pk"), subject__code__in=subjects))
        )
    cnj = params.get("cnj", "").strip()
    if cnj:
        if not re.fullmatch(r"[0-9]{20}|[0-9]{7}-[0-9]{2}\.[0-9]{4}\.[0-9]\.[0-9]{2}\.[0-9]{4}", cnj):
            raise InvalidQuery("Informe os 20 dígitos do número CNJ.")
        cnj = normalize_cnj_identifier(cnj)
        query = query.filter(process_dimension__number_process=cnj)
    degrees = options(params, "degree", DEGREES)
    if degrees:
        query = query.filter(degree_dimension__code__in=degrees)
    sources = options(params, "sources", SOURCES, SOURCES)
    outcomes = options(params, "outcomes", OUTCOMES, OUTCOMES)
    topics = options(params, "topics", TOPIC_LABELS)
    undated = params.get("undated", "true")
    if not sources or undated not in ("true", "false") or ("datajud" in sources and not outcomes):
        raise InvalidQuery("Selecione fontes e resultados válidos.")
    cohort = settings.RESEARCH_CIVIL_COHORT
    if cohort:
        query = query.filter(Exists(CivilSampleMember.objects.filter(fact=OuterRef("pk"), cohort__name=cohort)))
    if "datajud" not in sources:
        query = query.none()
    merit_query = query
    if "datajud" in sources and set(outcomes) != set(OUTCOMES):
        query = query.filter(
            result__name__in=[v if v != "outside_appellate_degree" else "outside_degree" for v in outcomes]
        )
    scope.update(
        selected_subject_codes=selected_subjects, subject_codes=subjects, cnj=cnj,
        topics=topics, sources=sources, outcomes=outcomes, degree=degrees, undated=undated == "true",
        cohort=cohort or None
    )
    indexed = scoped_items(scope, scope["undated"], all_dates=precedent_all_dates).filter(category__in=sources)
    if topics:
        indexed = indexed.filter(topic_matches__topic__in=topics).distinct()
    return query, scope, indexed, merit_query


def coverage(scope):
    cohort = CivilSamplingCohort.objects.filter(name=scope["cohort"]).first() if scope["cohort"] else None
    if not cohort:
        return None
    courts = scope["court"].split(",")
    members = CivilSampleMember.objects.filter(cohort=cohort, court__in=courts)
    bounds = members.values("court").annotate(first=Min("fact__time__date"), last=Max("fact__time__date"))
    by_court = {row["court"]: {"first": row["first"], "last": row["last"]} for row in bounds}
    first_year = max(int(scope["start"][:4]), cohort.definition["start_year"])
    last_year = int(scope["end"][:4])
    target = cohort.definition["target"]
    counts = {(c, y): n for c, y, n in members.filter(year__range=(first_year, last_year))
              .values("court", "year").annotate(n=Count("pk")).values_list("court", "year", "n")}
    failed = set()
    for run in ExtractionRun.objects.filter(scope__origin="civil_sampling", scope__cohort=cohort.name,
                                             scope__court__in=courts).values("scope", "status"):
        details = run["scope"]
        if run["status"] == "failed" or details.get("remote_scan", {}).get("errors"):
            failed.add((details["court"], details.get("year")))
    cells = []
    for year in range(first_year, last_year + 1):
        for court in courts:
            count = counts.get((court, year), 0)
            failure = (court, year) in failed
            state = "target_met" if count >= target else "partial" if count else "failed" if failure else "unverified"
            cells.append({"court": court, "year": year, "members": count, "state": state, "collection_failed": failure})
    return {"target_per_cell": target, "by_court": by_court, "cells": cells}


def context(params, question="", previous=()):
    query, scope, indexed, merit_query = selection(params)
    counts = {key: 0 for key in CATEGORIES}
    counts.update(dict(indexed.order_by().values_list("category").annotate(n=Count("pk", distinct=True))))
    docs = retrieve(indexed, question, previous)
    # Relation counts concern the complete selected set, independent of examples returned to the chat.
    usage = (
        usage_summary(scope, page_size=4)
        if {"precedent", "jurisprudence"}.issubset(scope["sources"])
        else None
    )
    if usage:
        for item in usage["items"]:
            docs.append(
                {
                    "id": "V" + item["id"],
                    "kind": "link",
                    "title": item["authority_literal"],
                    "origin": item["court"],
                    "date": item["decision_date"],
                    "excerpt": item["excerpt"],
                    "url": safe_url(item["source_url"]),
                    "relation": RELATIONS[item["status"]],
                }
            )
    values = metrics(query)
    return {
        "scope": scope,
        "metrics": values,
        "merit_baseline": summarize(merit_query) if set(scope["outcomes"]) != set(OUTCOMES) else {
            key: values[key] for key in ("binary_denominator", "granted", "denied", "grant_rate", "denial_rate", "excluded")
        },
        "history": instance_series(query),
        "counts": counts,
        "sources": docs,
        "usage": usage["counts"] if usage else None,
        "topics": TOPIC_LABELS,
        "provider": "gemini" if ai_ready() else "local",
    }


def retrieve(indexed, question, previous):
    # Earlier document mentions help with follow-ups, but can never extend the authorized queryset.
    direct = SOURCE_ID.findall(question)
    recent = previous[-1] if previous and follows_up(question) else ""
    ids = list(map(int, direct or SOURCE_ID.findall(recent)))
    inferred = classify(question) or classify(recent)
    if ids and not inferred:
        inferred = set(indexed.filter(pk__in=ids).values_list("topic_matches__topic", flat=True))
    if inferred and not direct:
        indexed = indexed.filter(topic_matches__topic__in=inferred).distinct()
    terms = list(dict.fromkeys(t for t in re.findall(r"[\w-]{4,}", question.lower()) if t not in STOP))[:8]
    score = Value(0, output_field=IntegerField())
    if ids:
        score += Case(When(pk__in=ids, then=100), default=0)
    if inferred:
        matches = LegalCorpusTopicMatch.objects.filter(item_id=OuterRef("pk"), topic__in=inferred)
        score += Case(When(Exists(matches), then=15), default=0)
    for term in terms:
        score += Case(When(title__icontains=term, then=3), When(public_excerpt__icontains=term, then=1), default=0)
    ranked = with_public_excerpt(indexed).annotate(relevance=score).order_by("-relevance", F("date").desc(nulls_last=True), "pk")
    docs = []
    for kind in CATEGORIES:
        for item in ranked.filter(category=kind)[:3]:
            docs.append(source_item(item))
    return docs


def source_item(item):
    permissions = item.provenance.get("permissions", {}) if isinstance(item.provenance, dict) else {}
    origin = item.source_name or item.court
    details = public_source_metadata(
        item.provenance,
        category=item.category,
        authors=item.authors,
        origin=origin,
        safe_url=safe_url,
    )
    return {
        "id": f"F{item.pk}",
        "kind": item.category,
        "title": item.title,
        "origin": origin,
        "court": item.court,
        "source_kind": item.content_kind,
        **details,
        "date": item.date,
        "date_kind": item.date_kind,
        "excerpt": item.excerpt[:1000] if permissions.get("text") == "allowed" else "",
        "url": safe_url(item.source_url),
        "authors": item.authors,
        "review_status": item.review_status,
    }


def ai_ready():
    return bool(
        settings.RESEARCH_GEMINI_ENABLED and settings.GEMINI_API_KEY and settings.RESEARCH_GEMINI_MODEL
    )


def block(text, refs=()):
    return {"text": text, "refs": list(refs)}


def number(n):
    return f"{n:,}".replace(",", ".")


def local_answer(data, question="", previous=()):
    phrase = folded(question)
    docs = data["sources"]
    m = data["metrics"]
    baseline = data["merit_baseline"]
    asked_ids = {f"F{i}" for i in SOURCE_ID.findall(question)}
    if asked_ids:
        found = [d for d in docs if d["id"] in asked_ids]
        return [
            block(d["excerpt"] or "A fonte tem apenas referência bibliográfica.", [d["id"]]) for d in found
        ] + [
            block(f"{i} não está entre os trechos recuperados neste recorte.")
            for i in sorted(asked_ids - {d["id"] for d in found})
        ]
    sections = []
    general = not question or any(term in phrase for term in ("resum", "sintese", "panorama"))
    if general or any(
        term in phrase for term in ("indicador", "taxa", "provimento", "quantos processos", "registros")
    ):
        if "datajud" not in data["scope"]["sources"]:
            sections.append(block("O DataJud está desmarcado neste recorte."))
        else:
            text = f"O DataJud reúne {number(m['process_records'])} registros por data de ajuizamento nos tribunais selecionados ({data['scope']['court']})."
            if baseline["binary_denominator"]:
                rate = f"{baseline['grant_rate'] * 100:.1f}%".replace(".", ",")
                text += f" Entre {number(baseline['binary_denominator'])} resultados elegíveis antes do filtro de resultado, houve {number(baseline['granted'])} providos e {number(baseline['denied'])} desprovidos. A taxa de provimento foi {rate}."
            else:
                text += " Não há resultados elegíveis para calcular a taxa de provimento."
            sections.append(block(text))
    if general or any(s in phrase for s in ("histor", "trimestr", "volume", "evolu")):
        quarters = Counter()
        for row in data["history"]:
            quarters[(row["time__year"], row["time__quarter"])] += row["count"]
        if quarters:
            peak = max(quarters.values())
            periods = [f"T{quarter}/{year}" for (year, quarter), n in sorted(quarters.items()) if n == peak]
            sections.append(
                block(f"O maior volume trimestral foi de {number(peak)} registros em {', '.join(periods)}.")
            )
        elif not general:
            sections.append(block("Sem registros de ajuizamento para compor o histórico."))
    kinds = [
        k
        for k, stem in (("doctrine", "doutrin"), ("precedent", "precedent"), ("jurisprudence", "decis"))
        if stem in phrase
    ]
    if general:
        kinds = ["precedent", "doctrine"]
    if "precedent" in kinds or any(s in phrase for s in ("afast", "aplica", "citad")):
        counts = data["usage"]
        if counts is not None:
            links = [d["id"] for d in docs if d["kind"] == "link"]
            sections.append(
                block(
                    f"O NLP identificou {counts['applied']} aplicações explícitas, {counts['not_applied']} afastamentos, {counts['mentioned']} menções e {counts['ambiguous']} vínculos ambíguos em ementas. Um vínculo temático por si só não prova aplicação.",
                    links[:2],
                )
            )
    for kind in kinds:
        examples = [d for d in docs if d["kind"] == kind]
        if not examples:
            sections.append(block(f"{TYPES[kind]}: nenhuma fonte no recorte selecionado."))
        else:
            doc = examples[0]
            sections.append(
                block(
                    f"{TYPES[kind]} · {doc['title']}. "
                    + (doc["excerpt"][:420] or "Item bibliográfico sem trecho indexado."),
                    [doc["id"]],
                )
            )
    if not sections:
        terms = set(re.findall(r"\w{4,}", phrase)) - STOP
        hits = [d for d in docs if any(t in folded(d["title"] + " " + d["excerpt"]) for t in terms)]
        for d in hits[:3]:
            sections.append(block(d["excerpt"][:420] or d["title"], [d["id"]]))
    return sections or [
        block(
            "Não encontrei um trecho que responda à pergunta. Indique um tema, o código de uma fonte ou um indicador do painel."
        )
    ]
