"""Offline CLI: python -m src.nlp --root ... --queue ... --output ..."""

import argparse
import json
import platform
import sys
from collections import Counter
from pathlib import Path

from .contracts import SCHEMA_VERSION, bytes_hash, canonical, fingerprint
from .extraction import RULES_VERSION
from .journal import Journal
from .pipeline import process


def write_immutable(path, value):
    data = (canonical(value) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"immutable_output_conflict: {path.name}")
    else:
        with path.open("xb") as stream:
            stream.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--guide", type=Path, required=True)
    parser.add_argument("--model-replay", type=Path)
    parser.add_argument("--allow-unreviewed-calibration", action="store_true")
    args = parser.parse_args()
    if not args.allow_unreviewed_calibration:
        parser.error("This experimental runner requires --allow-unreviewed-calibration; no production release.")
    queue_raw = args.queue.read_bytes()
    queue = json.loads(queue_raw)
    if not isinstance(queue, list) or not queue:
        parser.error("queue must be a nonempty array")
    replay = json.loads(args.model_replay.read_bytes()) if args.model_replay else None
    if replay is not None:
        required = {"model_id", "model_revision", "prompt_sha256", "parameters", "records"}
        if not isinstance(replay, dict) or not required <= replay.keys():
            parser.error("model replay requires frozen model/prompt/parameters and records")
        identities = [r["document_id"] for r in replay["records"]]
        if len(identities) != len(set(identities)):
            parser.error("duplicate model record document_id")
    package = Path(__file__).parent
    manifest = {
        "pipeline_version": "0.1.0", "schema_version": SCHEMA_VERSION,
        "rules_version": RULES_VERSION, "guide_version": "0.1.0", "taxonomy_version": "0.1.0",
        "guide_sha256": bytes_hash(args.guide.read_bytes()), "guide_approval": "not_verified",
        "code_hashes": {p.name: bytes_hash(p.read_bytes()) for p in sorted(package.glob("*.py"))},
        "prompt_sha256": bytes_hash((package / "prompt.txt").read_bytes()),
        "input_manifest_sha256": bytes_hash(queue_raw),
        "runtime": {"python": sys.version, "platform": platform.platform(), "dependencies": "stdlib_only"},
        "parameters": {"short_threshold": 200, "max_paragraph": 6000},
        "model": None if replay is None else {k: v for k, v in replay.items() if k != "records"},
        "model_replay_sha256": bytes_hash(args.model_replay.read_bytes()) if replay else None,
        "normalizer": "identity-v1", "segmenter": "blank-line-v1",
        "release_status": "experimental_not_evaluated",
    }
    run_dir = args.output / fingerprint(manifest)
    run_dir.mkdir(parents=True, exist_ok=True)
    write_immutable(run_dir / "manifest.json", manifest)
    journal = Journal(run_dir / "journal.sqlite3")
    records = {r["document_id"]: r for r in replay["records"]} if replay else {}
    outcomes, resumed = [], 0
    try:
        for row in queue:
            result, cached = process(row, args.root, manifest, journal, records.get(row.get("document_id")))
            # Content-addressed attempts preserve failure and later recovery independently.
            write_immutable(run_dir / (result["result_sha256"] + ".json"), result)
            outcomes.append(result)
            resumed += int(cached)
    finally:
        journal.close()
    summary = {
        "documents": len(outcomes), "resumed": resumed,
        "status_counts": dict(Counter(r["status"] for r in outcomes)),
        "court_counts": dict(Counter(r["source"].get("court") for r in outcomes)),
        "candidate_labels": dict(Counter(label for r in outcomes for a in r["annotations"] for label in a["labels"])),
        "result_hashes": [r["result_sha256"] for r in outcomes],
        "semantic_validation": "not_performed", "release": "blocked_pending_112_and_input_approvals",
    }
    write_immutable(run_dir / ("summary-" + fingerprint(summary) + ".json"), summary)
    print(json.dumps({"output": str(run_dir.resolve()), **summary}, ensure_ascii=False, indent=2))
    return 1 if any(r["status"] in ("failed", "missing_text") for r in outcomes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
