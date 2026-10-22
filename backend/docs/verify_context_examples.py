"""Check the hand-counted #165 oracle, without Django or any application database.

This is a contract review aid, not the #166 production parser/query implementation.
"""

import hashlib
import json
from collections import Counter
from fractions import Fraction
from pathlib import Path


def canonical(context):
    normalized = dict(context)
    for key in ("courts", "outcomes", "sources", "subject_codes"):
        normalized[key] = sorted(set(context[key]))
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False)


def query_id(context):
    return hashlib.sha256(canonical(context).encode("utf-8")).hexdigest()


def reconcile(fixture, case):
    context = json.loads(canonical(case["context"]))
    if set(context["courts"]) - set(case["authorized_courts"]):
        # No partial result or counts may escape a denied mixed court request.
        return {"error_status": 403}
    selected = set(context["sources"])
    available = set(case["available_sources"])
    subjects = set(context["subject_codes"])
    population = {
        row["id"]: row
        for row in fixture["documents"]
        if row["source"] in selected & available
        and row["court"] in context["courts"]
        and subjects.intersection(row["subject_codes"])
        and context["start"] <= row["filing_date"] <= context["end"]
    }
    counts = Counter(row["outcome"] for row in population.values())
    denominator = counts["granted"] + counts["denied"]
    rate = Fraction(counts["granted"], denominator) if denominator else None
    doctrine = {
        row["id"]
        for row in fixture["doctrine"]
        if row["source"] in selected & available
        and subjects.intersection(row["subject_codes"])
        and context["start"] <= row["publication_date"] <= context["end"]
    }
    return {
        "population_count": len(population),
        "granted": counts["granted"],
        "denied": counts["denied"],
        "binary_denominator": denominator,
        "grant_rate_fraction": [rate.numerator, rate.denominator] if rate is not None else None,
        "excluded": {key: value for key, value in counts.items() if key not in {"granted", "denied"}},
        "displayed_ids": sorted(
            identity for identity, row in population.items() if row["outcome"] in context["outcomes"]
        ),
        "doctrine_count": len(doctrine),
        "missing_sources": sorted(selected - available),
    }


def main():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "analytical-context-v1.json").read_text(encoding="utf-8")
    )
    cases = {case["name"]: case for case in fixture["cases"]}
    if len(cases) != len(fixture["cases"]):
        raise ValueError("Duplicate case identity")
    for name, case in cases.items():
        actual = reconcile(fixture, case)
        if actual != case["expected"]:
            raise ValueError(f"{name}: expected {case['expected']!r}, got {actual!r}")
    for first, second in fixture["equivalent_contexts"]:
        if query_id(cases[first]["context"]) != query_id(cases[second]["context"]):
            raise ValueError("Ordering and duplicate values changed the canonical identity")
    if query_id(cases["combined"]["context"]) == query_id(cases["mixed_outcomes"]["context"]):
        raise ValueError("Different display contexts have the same identity")
    print(json.dumps({"status": "passed", "synthetic": True, "cases": len(cases)}))


if __name__ == "__main__":
    main()
