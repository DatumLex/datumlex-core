"""Explainable lexical NLP and extractive summaries for source theses.

No legal equivalence or decision link is inferred from shared vocabulary.
"""
import re
from collections import Counter
from .topics import TOPICS, classify, folded

STOP = set('a o as os um uma de da do das dos e em no na nos nas por para com que se ao aos ou quando sera ser nao somente pelo pela sua seu'.split())
EXTRA = (('nexo causal', 'Nexo causal'), ('responsabilidade objetiva', 'Responsabilidade objetiva'),
         ('culpa exclusiva', 'Culpa exclusiva'), ('onus da prova', 'Ônus da prova'),
         ('prescricao', 'Prescrição'), ('cadastro de inadimplentes', 'Cadastro de inadimplentes'))

def describe_thesis(text):
    text = ' '.join((text or '').split())
    matches = classify(text)
    titles = [label for key, label, _ in TOPICS if key in matches]
    normalized = folded(text)
    terms = [term for values in matches.values() for term in values]
    for term, label in EXTRA:
        if re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', normalized):
            terms.append(term)
            if label not in titles:
                titles.append(label)
    if len(text) <= 65:
        title = text
    elif titles:
        title = titles[0]
    else:
        words = re.findall(r'[^\W\d_]+', text, re.UNICODE)
        keywords = Counter(word.lower() for word in words if len(word) > 3 and folded(word) not in STOP)
        title = ' · '.join(word for word, _ in keywords.most_common(4)).capitalize() or 'Tese para consulta'
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-ZÀ-Ú])', text)
    summary = sentences[0] if sentences else text
    return {'label': title[:65], 'summary': summary, 'nlp': {
        'method': 'lexical-extractive-v1', 'topics': titles, 'matched_terms': sorted(set(terms)),
        'summary_method': 'first_complete_sentence', 'requires_review': True,
    }}
