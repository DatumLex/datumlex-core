"""Conservative document-level outcome proxy; not a unique-appeal census."""

from collections import Counter

from django.db.models import Count

VERSION = "tpu-document-latest-v2"
# Deliberately limited to explicitly mapped TPU outcomes. See docs/merit-methodology.md.
CODES = {
    237: "granted",
    972: "granted",
    239: "denied",
    238: "partial",
    235: "not_admitted",
    240: "partial_knowledge",
    241: "partial_knowledge",
    242: "partial_knowledge",
}


def classify(process):
    evidence = [
        {"movement_id": movement.pk, "code": movement.code, "date": movement.occurred_at}
        for movement in process.movements.all()
        if movement.code in CODES
    ]
    dated = [item for item in evidence if item["date"] is not None]
    selected = max(dated, key=lambda item: (item["date"], item["movement_id"]), default=None)
    latest = [selected] if selected else []
    states = {CODES[item["code"]] for item in latest}
    if process.degree not in {"G2", "TR"}:
        outcome = "outside_appellate_degree"
    elif not states:
        outcome = "unknown"
    elif len(states) > 1:
        outcome = "ambiguous"
    else:
        outcome = states.pop()
    return {"outcome": outcome, "evidence": evidence, "selected_evidence": latest, "rule_version": VERSION}


def summarize(query):
    # The loader stores this classification atomically with the movement snapshot.
    # Aggregate it in SQL instead of loading every payload and movement into Python.
    # Distinct IDs also protect callers that join the multi-subject bridge.
    counts = Counter()
    for row in query.order_by().values("result__name").annotate(count=Count("pk", distinct=True)):
        name = row["result__name"]
        if name == "outside_degree":
            name = "outside_appellate_degree"
        counts[name] += row["count"]
    denominator = counts["granted"] + counts["denied"]
    return {
        "granted": counts["granted"],
        "denied": counts["denied"],
        "binary_denominator": denominator,
        "grant_rate": counts["granted"] / denominator if denominator else None,
        "denial_rate": counts["denied"] / denominator if denominator else None,
        "excluded": {
            key: counts[key]
            for key in (
                "partial",
                "not_admitted",
                "partial_knowledge",
                "ambiguous",
                "unknown",
                "outside_appellate_degree",
            )
        },
        "rule_version": VERSION,
        "rate_unit": "DataJud documents classified by latest dated mapped outcome in G2/TR",
    }
