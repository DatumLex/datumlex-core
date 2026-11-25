"""Real Portuguese statistical/neural NLP engine using spaCy (pt_core_news_sm) + scikit-learn TF-IDF."""

from collections import Counter
from functools import lru_cache
import re

import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import spacy

MODEL_NAME = "pt_core_news_sm"

ENTITY_LABELS_PT = {
    "ORG": "Organização / Órgão",
    "LOC": "Local / Jurisdição",
    "PER": "Pessoa",
    "MISC": "Norma / Referência",
}

LEGAL_STOPWORDS = frozenset(
    {
        "acordao", "acórdão", "acao", "ação", "apelacao", "apelação", "art", "artigo",
        "autos", "caso", "civil", "codigo", "código", "conforme", "decisao", "decisão",
        "desembargador", "direito", "ementa", "estado", "fls", "forma", "grau",
        "julgamento", "juiz", "justica", "justiça", "lei", "medida", "merito", "mérito",
        "ministro", "nao", "não", "nos", "numero", "número", "parte", "partes",
        "pedido", "poder", "processo", "recurso", "relator", "relatora", "sentenca",
        "sentença", "ser", "sobre", "ter", "termos", "tribunal", "turma", "vara",
        "voto", "pelo", "pela", "pelos", "pelas", "deste", "desta", "nesse", "nessa",
        "ainda", "assim", "bem", "como", "deve", "entre", "este", "esta", "isto",
        "mais", "pode", "pois", "porem", "porém", "quando", "que", "seu", "sua",
        "seus", "suas", "tambem", "também", "todo", "toda", "todos", "todas",
        "uma", "uns", "umas", "haver", "fazer", "dar", "ficar", "estar", "ir",
        "seria", "foi", "foram", "seja", "sendo", "tendo", "ha", "há",
        "recorrente", "recorrido", "apelante", "apelado", "autor", "autora", "reu", "réu",
        "agravante", "agravado", "embargante", "embargado", "impetrante", "impetrado",
        "publicacao", "publicação", "dje", "cnj", "nº", "n.", "r$", "inciso", "paragrafo",
        "parágrafo", "caput", "alínea", "alinea", "item", "itens",
    }
)

_WHITESPACE_RE = re.compile(r"\s+")
_NOISE_ENTITY_RE = re.compile(r"^[\W\d_]+$")


@lru_cache(maxsize=1)
def load_pipeline():
    """Load the official Portuguese spaCy pipeline once per worker process."""
    try:
        nlp = spacy.load(MODEL_NAME)
        loaded_model = MODEL_NAME
    except OSError:
        nlp = spacy.blank("pt")
        loaded_model = "spacy.blank('pt')"
    nlp.max_length = 200_000
    return nlp, loaded_model


def engine_info():
    nlp, loaded_model = load_pipeline()
    return {
        "library": "spaCy + scikit-learn",
        "spacy_version": spacy.__version__,
        "sklearn_version": sklearn.__version__,
        "model": loaded_model,
        "language": "pt",
        "components": [*nlp.pipe_names, "TfidfVectorizer", "cosine_similarity"],
    }


def _clean_text(text, max_chars=2500):
    compact = _WHITESPACE_RE.sub(" ", str(text or "")).strip()
    return compact[:max_chars]


def _extract_lemmas(doc, stopwords):
    lemmas = []
    pos_counts = Counter()
    for token in doc:
        if token.is_space or token.is_punct or token.like_num or token.is_stop:
            continue
        pos = token.pos_ or "TOKEN"
        pos_counts[pos] += 1
        if pos and pos not in ("NOUN", "PROPN", "ADJ", "VERB", "TOKEN"):
            continue
        lemma = (token.lemma_ or token.text).strip().lower()
        if len(lemma) < 3 or lemma in stopwords or not any(ch.isalpha() for ch in lemma):
            continue
        lemmas.append((lemma, pos))
    return lemmas, pos_counts


def analyze_text(text):
    """Run real spaCy tokenization, lemmatization, POS tagging and NER on a single text."""
    nlp, _ = load_pipeline()
    cleaned = _clean_text(text, max_chars=4000)
    if not cleaned:
        return {
            "engine": engine_info(),
            "token_count": 0,
            "sentence_count": 0,
            "lemmas": [],
            "entities": [],
            "pos_summary": {},
        }
    stopwords = nlp.Defaults.stop_words | LEGAL_STOPWORDS
    doc = nlp(cleaned)
    lemmas, pos_counts = _extract_lemmas(doc, stopwords)

    entity_counter = Counter()
    for ent in doc.ents:
        label = ent.label_
        ent_text = _WHITESPACE_RE.sub(" ", ent.text).strip()
        if len(ent_text) < 2 or len(ent_text) > 80 or _NOISE_ENTITY_RE.match(ent_text):
            continue
        entity_counter[(ent_text, label)] += 1

    unique_lemmas = []
    seen = set()
    for lemma, _pos in lemmas:
        if lemma not in seen:
            seen.add(lemma)
            unique_lemmas.append(lemma)

    try:
        sentence_count = sum(1 for _ in doc.sents)
    except ValueError:
        sentence_count = 1 if cleaned else 0

    return {
        "engine": engine_info(),
        "token_count": len(doc),
        "sentence_count": sentence_count,
        "lemmas": unique_lemmas[:20],
        "entities": [
            {
                "text": ent_text,
                "label": label,
                "label_pt": ENTITY_LABELS_PT.get(label, label),
                "count": count,
            }
            for (ent_text, label), count in entity_counter.most_common(12)
        ],
        "pos_summary": dict(pos_counts.most_common(6)),
    }


def analyze_corpus(documents, *, query="", top_terms=14, top_entities=12, top_similar=6, max_docs=100):
    """Analyze real legal texts with spaCy (NER + lemmatization) and scikit-learn (TF-IDF + cosine)."""
    nlp, _ = load_pipeline()
    stopwords = nlp.Defaults.stop_words | LEGAL_STOPWORDS
    usable = []
    for item in documents[:max_docs]:
        cleaned = _clean_text(item.get("text") or item.get("excerpt") or "", max_chars=2200)
        if len(cleaned) < 25:
            continue
        usable.append({**item, "_clean_text": cleaned})

    info = engine_info()
    if not usable:
        return {
            "engine": info,
            "query": (query or "").strip(),
            "corpus_stats": {
                "documents_analyzed": 0,
                "total_tokens": 0,
                "total_sentences": 0,
                "vocabulary_size": 0,
            },
            "top_tfidf_terms": [],
            "entities": [],
            "top_lemmas": [],
            "similar_documents": [],
        }

    texts = [item["_clean_text"] for item in usable]
    lemma_docs = []
    lemma_counter = Counter()
    entity_counter = Counter()
    total_tokens = 0
    total_sentences = 0

    for doc in nlp.pipe(texts, batch_size=20):
        total_tokens += len(doc)
        try:
            total_sentences += sum(1 for _ in doc.sents)
        except ValueError:
            total_sentences += 1
        lemmas, _ = _extract_lemmas(doc, stopwords)
        lemma_docs.append(" ".join(lemma for lemma, _ in lemmas))
        for lemma, pos in lemmas:
            if pos in ("NOUN", "PROPN", "ADJ", "TOKEN"):
                lemma_counter[(lemma, pos)] += 1
        for ent in doc.ents:
            ent_text = _WHITESPACE_RE.sub(" ", ent.text).strip()
            if len(ent_text) < 2 or len(ent_text) > 70 or _NOISE_ENTITY_RE.match(ent_text):
                continue
            entity_counter[(ent_text, ent.label_)] += 1

    non_empty_docs = [d for d in lemma_docs if d.strip()]
    top_tfidf_terms = []
    similar_documents = []
    vocab_size = 0

    if non_empty_docs:
        min_df = 2 if len(non_empty_docs) >= 6 else 1
        vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            min_df=min_df,
            max_df=0.92 if len(non_empty_docs) >= 6 else 1.0,
            max_features=800,
            sublinear_tf=True,
            token_pattern=r"(?u)\b[a-zA-ZÀ-ÿ]{3,}\b",
        )
        try:
            matrix = vectorizer.fit_transform(lemma_docs)
            feature_names = vectorizer.get_feature_names_out()
            vocab_size = len(feature_names)
            mean_scores = matrix.mean(axis=0).A1
            doc_freqs = (matrix > 0).sum(axis=0).A1
            ranked_idx = mean_scores.argsort()[::-1][:top_terms]
            top_tfidf_terms = [
                {
                    "term": str(feature_names[idx]),
                    "score": round(float(mean_scores[idx]), 4),
                    "doc_count": int(doc_freqs[idx]),
                }
                for idx in ranked_idx
                if mean_scores[idx] > 0
            ]

            clean_query = _clean_text(query, max_chars=500)
            if clean_query:
                q_doc = nlp(clean_query)
                q_lemmas, _ = _extract_lemmas(q_doc, stopwords)
                q_repr = " ".join(lemma for lemma, _ in q_lemmas) or clean_query.lower()
                q_vec = vectorizer.transform([q_repr])
                sims = cosine_similarity(q_vec, matrix).ravel()
                for idx in sims.argsort()[::-1][:top_similar]:
                    score = float(sims[idx])
                    if score <= 0.01:
                        continue
                    src = usable[idx]
                    similar_documents.append(
                        {
                            "id": src.get("id", ""),
                            "title": src.get("title", ""),
                            "court": src.get("court", ""),
                            "category": src.get("category", "jurisprudence"),
                            "date": src.get("date"),
                            "url": src.get("url", ""),
                            "similarity": round(score, 4),
                            "snippet": src["_clean_text"][:320],
                        }
                    )
        except ValueError:
            vocab_size = 0

    return {
        "engine": info,
        "query": (query or "").strip(),
        "corpus_stats": {
            "documents_analyzed": len(usable),
            "total_tokens": total_tokens,
            "total_sentences": total_sentences,
            "vocabulary_size": vocab_size,
        },
        "top_tfidf_terms": top_tfidf_terms,
        "entities": [
            {
                "text": ent_text,
                "label": label,
                "label_pt": ENTITY_LABELS_PT.get(label, label),
                "count": count,
            }
            for (ent_text, label), count in entity_counter.most_common(top_entities)
        ],
        "top_lemmas": [
            {"lemma": lemma, "pos": pos, "count": count}
            for (lemma, pos), count in lemma_counter.most_common(12)
        ],
        "similar_documents": similar_documents,
    }
