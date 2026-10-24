"""Versioned interchange contract; independent from the pending #104 migrations."""

import hashlib
import json

SCHEMA_VERSION = "0.1.0"
LABELS = {"LEGAL_THESIS", "LEGAL_GROUND", "CITED_AUTHORITY", "CASE_HOLDING", "JUDGMENT_OUTCOME"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def bytes_hash(value):
    return hashlib.sha256(value).hexdigest()


def fingerprint(value):
    return bytes_hash(canonical(value).encode("utf-8"))


def unknown(reason="not_established"):
    return {"value": None, "value_status": "unknown", "reason": reason}


def validate_annotation(annotation, text):
    labels = annotation["labels"]
    if not labels or not set(labels) <= LABELS:
        raise ValueError("invalid_labels")
    if annotation["label_status"] != "proposed":
        raise ValueError("automatic_approval_forbidden")
    segments = annotation["segments"]
    if not segments:
        raise ValueError("missing_segments")
    previous_end = -1
    for segment in segments:
        start, end = segment["start"], segment["end"]
        if type(start) is not int or type(end) is not int:
            raise ValueError("non_integer_offset")
        if not 0 <= start < end <= len(text) or start < previous_end:
            raise ValueError("invalid_offset")
        if text[start:end] != segment["text"]:
            raise ValueError("quote_mismatch")
        previous_end = end


def validate_result(result, text):
    if result["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported_schema")
    if result["evaluation"]["status"] != "not_evaluated":
        raise ValueError("evaluation_claim_forbidden")
    if text is not None:
        if result["text"]["sha256"] != bytes_hash(text.encode("utf-8")):
            raise ValueError("result_text_hash_mismatch")
        for annotation in result["annotations"]:
            validate_annotation(annotation, text)
    elif result["annotations"]:
        raise ValueError("evidence_without_text")
    ids = [a["id"] for a in result["annotations"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_annotation_id")
    if result["relations"]:
        raise ValueError("relations_not_supported_in_v0")
