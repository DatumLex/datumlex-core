"""Read and reconcile the #111 queue against its actual local source artifacts."""

import json
from pathlib import Path

from .contracts import bytes_hash


class SourceProblem(ValueError):
    pass


def read_source(row, root):
    root = Path(root).resolve()
    path = (root / row["artifact_path"]).resolve()
    if not path.is_relative_to(root):
        raise SourceProblem("artifact_outside_workspace")
    raw = path.read_bytes()
    if bytes_hash(raw) != row["artifact_sha256"]:
        raise SourceProblem("artifact_hash_mismatch")
    if row["court"] == "STJ":
        if path.suffix.lower() != ".txt":
            raise SourceProblem("pdf_requires_traceable_extractor")
        text = raw.decode("utf-8", errors="strict")
    elif row["court"] == "TJDFT":
        if row.get("text_field") != "inteiroTeor":
            raise SourceProblem("unsupported_text_representation")
        uuid = row["document_id"].removeprefix("TJDFT:")
        records = [r for r in json.loads(raw)["registros"] if r["uuid"] == uuid]
        if len(records) != 1:
            raise SourceProblem("ambiguous_document")
        if records[0].get("segredoJustica") is not False:
            raise SourceProblem("source_eligibility_requires_review")
        text = records[0].get("inteiroTeor")
    else:
        raise SourceProblem("unsupported_court")
    if text is None or text == "":
        raise SourceProblem("missing_text")
    if not isinstance(text, str):
        raise SourceProblem("invalid_text_type")
    if not text.strip():
        raise SourceProblem("missing_text")
    if "\x00" in text:
        raise SourceProblem("invalid_nul_character")
    if bytes_hash(text.encode("utf-8")) != row["text_sha256"]:
        raise SourceProblem("text_hash_mismatch")
    if "source_text" in row and row["source_text"] != text:
        raise SourceProblem("queue_source_disagreement")
    return text
