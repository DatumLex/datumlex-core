"""Offline CLI: python -m src.nlp --root ... --queue ... --output ..."""

import argparse
import json
import os
import platform
import sys
from collections import Counter
from pathlib import Path

from .contracts import SCHEMA_VERSION, bytes_hash, canonical, fingerprint
from .extraction import RULES_VERSION
from .journal import Journal
from .cache import ComputationCache
from .pipeline import process


def write_immutable(path, value):
    data = (canonical(value) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"immutable_output_conflict: {path.name}")
    else:
        temporary=path.with_name(path.name+'.part')
        with temporary.open('wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--guide", type=Path, required=True)
    parser.add_argument("--model-replay", type=Path)
    parser.add_argument("--computation-cache", type=Path)
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
    code_sources = {p.name:p.read_bytes() for p in sorted(package.glob("*.py"))}
    manifest = {
        "pipeline_version": "0.4.0", "schema_version": SCHEMA_VERSION,
        "rules_version": RULES_VERSION, "guide_version": "0.1.0", "taxonomy_version": "0.1.0",
        "guide_sha256": bytes_hash(args.guide.read_bytes()), "guide_approval": "not_verified",
        "code_hashes": {name:bytes_hash(raw) for name,raw in code_sources.items()},
        "prompt_sha256": bytes_hash((package / "prompt.txt").read_bytes()),
        "input_manifest_sha256": bytes_hash(queue_raw),
        "runtime": {"python": sys.version, "platform": platform.platform(), "dependencies": "stdlib_only"},
        "parameters": {"short_threshold": 200, "max_paragraph": 6000},
        "model": None if replay is None else {k: v for k, v in replay.items() if k != "records"},
        "model_replay_sha256": bytes_hash(args.model_replay.read_bytes()) if replay else None,
        "normalizer": "identity-v1", "segmenter": "blank-line-html-break-v2",
        "release_status": "experimental_not_evaluated",
    }
    run_dir = args.output / fingerprint(manifest)
    run_dir.mkdir(parents=True, exist_ok=True)
    write_immutable(run_dir / "manifest.json", manifest)
    code_dir=run_dir/'code';code_dir.mkdir(exist_ok=True)
    for name,raw in code_sources.items():
        target=code_dir/name
        if target.exists() and target.read_bytes()!=raw:raise ValueError('immutable_code_snapshot_conflict')
        if not target.exists():target.write_bytes(raw)
    guide_target=run_dir/'guide.txt'
    guide_raw=args.guide.read_bytes()
    if bytes_hash(guide_raw)!=manifest['guide_sha256']:raise ValueError('Guide changed during startup')
    if not guide_target.exists():guide_target.write_bytes(guide_raw)
    journal = Journal(run_dir / "journal.sqlite3")
    cache = ComputationCache(args.computation_cache) if args.computation_cache else None
    records = {r["document_id"]: r for r in replay["records"]} if replay else {}
    documents=resumed=0
    statuses,courts,labels=Counter(),Counter(),Counter()
    hashes=[]
    has_failures=False
    try:
        for row in queue:
            result, cached = process(row, args.root, manifest, journal, records.get(row.get("document_id")), computation_cache=cache)
            # Content-addressed attempts preserve failure and later recovery independently.
            result_dir = run_dir / 'results' / result['result_sha256'][:2]
            result_dir.mkdir(parents=True, exist_ok=True)
            write_immutable(result_dir / (result["result_sha256"] + ".json"), result)
            documents+=1;statuses[result['status']]+=1;courts[result['source'].get('court')]+=1
            labels.update(label for annotation in result['annotations'] for label in annotation['labels'])
            hashes.append(result['result_sha256']);has_failures|=result['status'] in ('failed','missing_text')
            resumed += int(cached)
            if documents%250==0:
                print(json.dumps({'phase':'nlp','processed':documents,'cached':resumed,'selected':len(queue)}),file=sys.stderr,flush=True)
    finally:
        journal.close()
        if cache is not None:
            cache.close()
    summary = {
        "documents": documents, "resumed": resumed,
        "status_counts": dict(statuses),
        "court_counts": dict(courts),
        "candidate_labels": dict(labels),
        "result_hashes": hashes,
        "semantic_validation": "not_performed", "release": "blocked_pending_112_and_input_approvals",
    }
    write_immutable(run_dir / ("summary-" + fingerprint(summary) + ".json"), summary)
    print(json.dumps({"output": str(run_dir.resolve()), **summary}, ensure_ascii=False, indent=2))
    return int(has_failures)


if __name__ == "__main__":
    raise SystemExit(main())
