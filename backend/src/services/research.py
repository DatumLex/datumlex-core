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
from src.nlp import engine as nlp_engine
from src.nlp.topics import TOPICS, classify, folded
from src.services.analytical_context import OUTCOMES
from src.services.corpus_catalog import CATEGORIES, safe_url, scoped_items
from src.services.corpus_publication import with_public_excerpt
from src.services.precedent_usage import summarize as usage_summary
from src.services.source_metadata import public_source_metadata
from src.services.statistics_service import InvalidQuery, filtered_processes, instance_series, metrics
from src.services.outcomes import summarize


TOPIC_LABELS = {key: label for key, label, _ in TOPICS}
INTENT_LABELS = {
    "overview": "Visão geral do recorte",
    "outcomes": "Análise de mérito e taxa de provimento",
    "history": "Evolução temporal e volume",
    "sources": "Fontes jurídicas do recorte",
}
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


CATEGORY_STEMS = (
    ("doctrine", ("doutrin", "artig", "ril")),
    ("precedent", ("precedent", "sumul", "tema repetitiv", "temas repetitiv")),
    ("jurisprudence", ("jurisprud", "ementa", "acordao", "decis")),
)
MAX_SAFE_EXCERPT = 25000


def strip_source_ids(text):
    return SOURCE_ID.sub("", text or "").strip()


def requested_categories(question):
    phrase = folded(question or "")
    return {
        category
        for category, stems in CATEGORY_STEMS
        if any(stem in phrase for stem in stems)
    }


def follows_up(question):
    return bool(
        re.search(
            r"(?:^e\s)|(?:\b(?:isso|nesse|nessa|desse|dessa|mesmo tema|sobre ele|sobre ela)\b)",
            folded(question),
        )
    )


def explicit_anaphora(question):
    return bool(
        re.search(r"\b(sobre isso|nesse|nessa|desse|dessa|mesmo tema|sobre ele|sobre ela)\b", folded(question))
    )


def question_scope(params, question, previous):
    courts = set(params.get("court", "TJDFT").split(","))
    named = set(re.findall(r"\b[A-Z]{2,8}\b", question.upper())) & set(ACTIVE_COURTS)
    inherited_courts = []
    if not named and previous and follows_up(question):
        prev_text = strip_source_ids(previous[-1])
        prev_named = set(re.findall(r"\b[A-Z]{2,8}\b", prev_text.upper())) & set(ACTIVE_COURTS)
        # Only inherit court narrowing if not switching broad category without repeating the court
        if prev_named and not requested_categories(question):
            named = prev_named
            inherited_courts = sorted(prev_named)
    if named - courts:
        raise InvalidQuery("O tribunal mencionado está fora deste recorte. Ajuste os filtros da pesquisa.")
    filtered = params.copy()
    if named:
        filtered["court"] = ",".join(sorted(named))
    if inherited_courts:
        filtered._inherited_courts = inherited_courts
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


def lexical_nlp_analysis(query, *, question="", intent_id="overview"):
    """Lexical NLP over user query and real DataJud TPU subject metadata (not full-text thesis extraction)."""
    query_matches = classify(question) if question else {}
    query_topics = [
        {"id": key, "label": TOPIC_LABELS[key], "matched_terms": terms}
        for key, terms in query_matches.items()
    ]
    subject_names = dict(
        FactProcessSubject.objects.filter(process__in=query)
        .values_list("subject_id", "subject__name")
        .distinct()
    )
    topic_subjects = {}
    topic_terms = {}
    for sid, name in subject_names.items():
        for key, terms in classify(name or "").items():
            topic_subjects.setdefault(key, set()).add(sid)
            topic_terms.setdefault(key, set()).update(terms)
    scope_topics = []
    for key, label, _ in TOPICS:
        sids = topic_subjects.get(key)
        if not sids:
            continue
        docs = (
            FactProcessSubject.objects.filter(process__in=query, subject_id__in=sids)
            .values("process_id")
            .distinct()
            .count()
        )
        if docs:
            scope_topics.append(
                {
                    "id": key,
                    "label": label,
                    "documents": docs,
                    "matched_terms": sorted(topic_terms[key]),
                }
            )
    scope_topics.sort(key=lambda item: (-item["documents"], item["id"]))
    spacy_analysis = nlp_engine.analyze_text(question) if question else None
    return {
        "method": "spacy_tfidf_and_metadata_nlp",
        "engine": nlp_engine.engine_info(),
        "intent": intent_id if intent_id in INTENT_LABELS else "overview",
        "intent_label": INTENT_LABELS.get(intent_id, INTENT_LABELS["overview"]),
        "query_topics": query_topics,
        "query_lemmas": spacy_analysis["lemmas"][:10] if spacy_analysis else [],
        "query_entities": spacy_analysis["entities"][:8] if spacy_analysis else [],
        "scope_metadata_topics": scope_topics,
        "limitation": (
            "Processamento de linguagem natural com spaCy (pt_core_news_sm) sobre a pergunta "
            "combinado aos assuntos TPU oficiais DataJud. Para extração de teses e TF-IDF sobre "
            "decisões reais, consulte a aba NLP · Teses."
        ),
    }


def context(params, question="", previous=()):
    query, scope, indexed, merit_query = selection(params)
    counts = {key: 0 for key in CATEGORIES}
    counts.update(dict(indexed.order_by().values_list("category").annotate(n=Count("pk", distinct=True))))
    docs, inherited_topics = retrieve_with_context(indexed, question, previous)
    inherited = {}
    inherited_courts = getattr(params, "_inherited_courts", None)
    if inherited_courts:
        inherited["courts"] = inherited_courts
    if inherited_topics:
        inherited["topics"] = [TOPIC_LABELS.get(t, t) for t in sorted(inherited_topics)]
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
        "inherited_context": inherited,
        "usage": usage["counts"] if usage else None,
        "topics": TOPIC_LABELS,
        "nlp": lexical_nlp_analysis(query, question=question),
        "provider": "gemini" if ai_ready() else "local",
        "gemini_cooldown_seconds": getattr(settings, "RESEARCH_GEMINI_COOLDOWN_SECONDS", 8),
    }


def retrieve(indexed, question, previous):
    docs, _ = retrieve_with_context(indexed, question, previous)
    return docs


def retrieve_with_context(indexed, question, previous):
    # Earlier document mentions help with follow-ups, but switching explicit categories must never
    # silently inherit IDs or topics from the prior category's sources (fix C01).
    direct = SOURCE_ID.findall(question)
    is_followup = bool(previous and follows_up(question))
    has_anaphora = bool(previous and explicit_anaphora(question))
    recent = previous[-1] if is_followup else ""
    recent_text = strip_source_ids(recent)
    asked_categories = requested_categories(question)
    prev_categories = requested_categories(recent_text) if recent_text else set()
    switching_category = bool(asked_categories and (not prev_categories or asked_categories != prev_categories))

    # Inherit F<id> references only when explicitly referenced or using explicit anaphora ("sobre isso", "desse", etc.)
    if direct:
        ids = list(map(int, direct))
    elif has_anaphora or (is_followup and not asked_categories):
        ids = list(map(int, SOURCE_ID.findall(recent)))
    else:
        ids = []

    question_topics = set(classify(question).keys())
    prev_question_topics = set(classify(recent_text).keys()) if is_followup else set()
    inherited_topics = set()

    if question_topics:
        inferred = question_topics
    elif prev_question_topics:
        inferred = prev_question_topics
        inherited_topics = set(prev_question_topics)
    elif ids and (has_anaphora or (not switching_category and not asked_categories)):
        inferred = {t for t in indexed.filter(pk__in=ids).values_list("topic_matches__topic", flat=True) if t}
        inherited_topics = set(inferred)
    else:
        inferred = set()

    filtered = indexed
    if inferred and not direct:
        narrowed = indexed.filter(topic_matches__topic__in=inferred).distinct()
        # Never hide existing sources of an explicitly requested category due to inherited continuation filters
        if inherited_topics and asked_categories and not narrowed.filter(category__in=asked_categories).exists():
            if indexed.filter(category__in=asked_categories).exists():
                inferred = set()
                inherited_topics = set()
                filtered = indexed
            else:
                filtered = narrowed
        else:
            filtered = narrowed

    terms = list(dict.fromkeys(t for t in re.findall(r"[\w-]{4,}", question.lower()) if t not in STOP))[:8]
    score = Value(0, output_field=IntegerField())
    if ids:
        score += Case(When(pk__in=ids, then=100), default=0)
    if inferred:
        matches = LegalCorpusTopicMatch.objects.filter(item_id=OuterRef("pk"), topic__in=inferred)
        score += Case(When(Exists(matches), then=15), default=0)
    for term in terms:
        score += Case(When(title__icontains=term, then=3), When(public_excerpt__icontains=term, then=1), default=0)
    ranked = with_public_excerpt(filtered).annotate(relevance=score).order_by("-relevance", F("date").desc(nulls_last=True), "pk")
    docs = []
    for kind in CATEGORIES:
        limit = 5 if kind in asked_categories else 3
        for item in ranked.filter(category=kind)[:limit]:
            docs.append(source_item(item))
    return docs, inherited_topics


def source_item(item, *, max_excerpt=MAX_SAFE_EXCERPT):
    permissions = item.provenance.get("permissions", {}) if isinstance(item.provenance, dict) else {}
    origin = item.source_name or item.court
    details = public_source_metadata(
        item.provenance,
        category=item.category,
        authors=item.authors,
        origin=origin,
        safe_url=safe_url,
    )
    text_allowed = permissions.get("text") == "allowed"
    raw_excerpt = item.excerpt or ""
    if text_allowed:
        excerpt = raw_excerpt if max_excerpt is None else raw_excerpt[:max_excerpt]
        truncated = len(raw_excerpt) > len(excerpt)
    else:
        excerpt = ""
        truncated = False
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
        "excerpt": excerpt,
        "excerpt_truncated": truncated,
        "excerpt_total_length": len(raw_excerpt) if text_allowed else 0,
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
        for k in ("doctrine", "precedent", "jurisprudence")
        if k in requested_categories(question)
    ]
    if general:
        kinds = ["precedent", "doctrine"]
    if "precedent" in kinds or any(s in phrase for s in ("afast", "aplica", "citad")):
        counts = data["usage"]
        if counts is not None and any(counts.values()):
            links = [d["id"] for d in docs if d["kind"] == "link"]
            sections.append(
                block(
                    f"O NLP identificou {counts['applied']} aplicações explícitas, {counts['not_applied']} afastamentos, {counts['mentioned']} menções e {counts['ambiguous']} vínculos ambíguos em ementas. Um vínculo temático por si só não prova aplicação.",
                    links[:2],
                )
            )
    for kind in kinds:
        examples = [d for d in docs if d["kind"] == kind]
        total_in_scope = (data.get("counts") or {}).get(kind, 0)
        if not examples:
            if total_in_scope > 0:
                sections.append(
                    block(
                        f"{TYPES[kind]}: há {number(total_in_scope)} fonte(s) aprovada(s) no recorte geral, "
                        "mas nenhuma coincidiu diretamente com os termos específicos desta pergunta. Consulte a aba Acervo para ver todas."
                    )
                )
            else:
                sections.append(block(f"{TYPES[kind]}: nenhuma fonte no recorte selecionado."))
        else:
            for doc in examples[:3]:
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
