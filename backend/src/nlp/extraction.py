"""Weak candidate retrieval, never a determination of judicial adoption."""

import re

from .contracts import fingerprint, unknown, validate_annotation

RULES_VERSION = "0.1.0"
AUTHORITY_RULES = {
    "sumula": r"\bS[úu]mula\s+(?:n[.º°o]*\s*)?\d+\s*(?:do\s+|/\s*)(?:STJ|STF)\b",
    "judgment": r"\b(?:REsp|AREsp)\s+(?:n[.º°o]*\s*)?\d[\d.]*\s*/\s*[A-Z]{2}\b",
    "statute": r"\bLei\s+(?:n[.º°o]*\s*)?\d[\d.]*(?:\s*/\s*\d{2,4})?\b",
    "provision": r"\bart(?:igo|\.)\s*\d+[A-Za-zº°]*(?:\s*,\s*§\s*\d+[º°]*)?\s+(?:do|da)\s+(?:CPC|CC|CDC|CF)\b",
}
TOPIC = re.compile(
    r"responsabilidade\s+civil|nexo\s+causal|danos?\s+(?:mora(?:l|is)|materia(?:l|is))|"
    r"dever\s+de\s+indenizar|culpa\s+(?:exclusiva|concorrente)|risco\s+da\s+atividade",
    re.I,
)
THESIS = re.compile(r"\b(?:exige|depende|independe|pressupõe|configura|necessári[oa]|deve[m]?|somente)\b", re.I)
GROUND = re.compile(r"\b(?:porque|pois|uma vez que|tendo em vista|nos termos|porquanto|em razão)\b", re.I)


def annotation(text, labels, segments, method, rule_id=None):
    item = {
        "labels": sorted(labels), "label_status": "proposed",
        "segments": [{"start": s, "end": e, "text": quote,
                      "locator": {"text_line_start": text.count("\n", 0, s) + 1,
                                  "text_line_end": text.count("\n", 0, e - 1) + 1,
                                  "page": None, "artifact_location_status": "unknown"}}
                     for s, e, quote in segments],
        "method": {"kind": method, "rule_id": rule_id},
        "context": {k: unknown() for k in (
            "speaker", "voice_id", "evaluating_voice_id", "adoption", "question_type",
            "argument_role", "polarity", "scope", "thesis_form", "topics")},
        "confidence": {"score": None, "calibration_id": None},
        "evidence_status": "unassessed", "review_status": "pending",
    }
    validate_annotation(item, text)
    item["id"] = fingerprint(item)
    return item


def paragraphs(text):
    # Keep original intervals; trimming affects selection only, never source text.
    start = 0
    for boundary in re.finditer(r"(?:\r?\n)[ \t\r]*(?:\n)", text):
        if boundary.start() > start:
            yield start, boundary.start()
        start = boundary.end()
    if start < len(text):
        yield start, len(text)


def extract(text, max_paragraph=6000):
    annotations, skipped = [], []
    for kind, pattern in AUTHORITY_RULES.items():
        for match in re.finditer(pattern, text, flags=re.I):
            item = annotation(text, ["CITED_AUTHORITY"],
                              [(match.start(), match.end(), match.group())], "rule", kind)
            item["authority"] = {
                "literal": match.group(), "kind": kind, "resolution_status": "unresolved",
                "resolved_id": None, "verification_source": None, "precedential_status": None,
            }
            annotations.append(item)
    for start, end in paragraphs(text):
        fragment = text[start:end]
        if len(fragment) > max_paragraph:
            skipped.append([start, end])
            continue
        if not TOPIC.search(fragment):
            continue
        for label, trigger in (("LEGAL_THESIS", THESIS), ("LEGAL_GROUND", GROUND)):
            if trigger.search(fragment):
                item = annotation(text, [label], [(start, end, fragment)], "weak_rule", label)
                item["warnings"] = ["paragraph_candidate_not_minimal_proposition", "attribution_unresolved"]
                annotations.append(item)
    return annotations, skipped


def replay_predictions(text, predictions):
    """Validate archived model proposals. Never fuzzy-match or repair quotations."""
    accepted, rejected = [], []
    for index, proposal in enumerate(predictions):
        try:
            accepted.append(annotation(
                text, proposal["labels"],
                [(s["start"], s["end"], s["text"]) for s in proposal["segments"]],
                "model_replay",
            ))
        except (KeyError, TypeError, ValueError) as exc:
            rejected.append({"index": index, "code": type(exc).__name__, "reason": str(exc)})
    return accepted, rejected
