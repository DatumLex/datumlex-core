"""Versioned per-document processing. All outputs are experimental candidates."""

from .adapters import read_source
from .contracts import SCHEMA_VERSION, fingerprint, validate_result
from .extraction import extract, replay_predictions


def process(row, root, manifest, journal, model_record=None):
    metadata = {k: v for k, v in row.items() if k not in ("source_text", "human_annotations", "adjudication")}
    key = fingerprint({"input": metadata, "pipeline": manifest, "model_record": model_record})
    result = {
        "schema_version": SCHEMA_VERSION, "job_key": key,
        "document_id": row.get("document_id"), "source_version": row.get("source_version"),
        "source": metadata, "pipeline": manifest,
        "text": {"sha256": row.get("text_sha256"), "offset_unit": "unicode_code_point",
                 "representation": row.get("text_field") or "utf8_txt", "normalization": "identity-v1"},
        "status": "failed", "annotations": [], "relations": [], "warnings": [],
        "errors": [], "rejected_candidates": [],
        "coverage": {"relations": "not_supported", "semantic_validation": "not_performed"},
        "review": {"status": "pending"},
        "evaluation": {"status": "not_evaluated", "release_id": None},
    }
    # Always reread and verify the artifact, even on resume. Never conceal deletion/change.
    try:
        text = read_source(row, root)
        cached = journal.get(key)
        if cached is not None:
            validate_result(cached, text)
            return cached, True
        result["text"]["characters"] = len(text)
        if len(text.strip()) < manifest["parameters"]["short_threshold"]:
            result["warnings"].append("short_text")
        if "\ufffd" in text:
            result["warnings"].append("replacement_character_requires_review")
        result["warnings"].extend(["eligibility_pending_legal_triage", "guide_approval_pending"])
        if not row.get("source_url"):
            result["warnings"].append("source_url_not_reconciled")
        annotations, skipped = extract(text, manifest["parameters"]["max_paragraph"])
        result["coverage"].update({
            "authority_scanned_intervals": [[0, len(text)]],
            "semantic_skipped_intervals": skipped,
            "thesis_ground_method": "weak_candidate_retrieval_not_semantic_classification",
            "case_holding_outcome": "model_replay_only" if model_record else "not_supported",
        })
        if model_record is not None:
            if (model_record["text_sha256"] != row["text_sha256"]
                    or model_record["document_id"] != row["document_id"]):
                raise ValueError("model_source_mismatch")
            proposed, rejected = replay_predictions(text, model_record["annotations"])
            annotations.extend(proposed)
            result["rejected_candidates"] = rejected
        # Same span/label/method is one occurrence. Different methods remain separate.
        result["annotations"] = sorted(
            {a["id"]: a for a in annotations}.values(),
            key=lambda a: (a["segments"][0]["start"], a["id"]),
        )
        result["status"] = "partial" if skipped or result["rejected_candidates"] else "completed"
        validate_result(result, text)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        # Failed inputs never masquerade as negative NLP predictions.
        result["annotations"] = []
        result["status"] = "missing_text" if str(exc) == "missing_text" else "failed"
        result["errors"] = [{"code": type(exc).__name__, "reason": str(exc)}]
    result["result_sha256"] = fingerprint(result)
    # Deterministic partial outputs (oversize spans/rejected proposals) can be resumed.
    # Fixing rules/model/text changes the job key. Input failures are always retried.
    journal.record(key, result, reusable=result["status"] in ("completed", "partial"))
    return result, False
