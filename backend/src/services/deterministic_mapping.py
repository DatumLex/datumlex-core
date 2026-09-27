"""Exact, evidence-backed mapping. No fuzzy matching or inferred legal labels."""

import hashlib
import json

FIELDS = ("code", "name", "complement")


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def validate_rules(document):
    if not isinstance(document, dict) or not isinstance(document.get("rule_version"), str):
        raise ValueError("Rules require a string rule_version")
    if not document["rule_version"].strip() or not isinstance(document.get("rules"), list):
        raise ValueError("Rules require a nonempty version and a rules list")
    identifiers = set()
    for rule in document["rules"]:
        if not isinstance(rule, dict):
            raise ValueError("Each rule must be an object")
        identity = rule.get("id")
        if not isinstance(identity, str) or not identity.strip() or identity in identifiers:
            raise ValueError("Rule IDs must be unique nonempty strings")
        identifiers.add(identity)
        if not isinstance(rule.get("target"), str) or not rule["target"].strip():
            raise ValueError("Each rule requires a target")
        matches = rule.get("match")
        if not isinstance(matches, dict) or not matches or set(matches) - set(FIELDS):
            raise ValueError("match must contain code, name and/or complement")
        if any(value is None or value == "" or value == [] or value == {} for value in matches.values()):
            raise ValueError("Empty match values are not allowed")
        evidence = rule.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("Each rule requires evidence")
        for item in evidence:
            if not isinstance(item, dict) or not any(
                isinstance(item.get(key), str) and item[key].strip() for key in ("source", "file")
            ):
                raise ValueError("Evidence requires a source or file")
            if "line" in item and (type(item["line"]) is not int or item["line"] < 1):
                raise ValueError("Evidence line must be a positive integer")
    canonical(document)


def map_record(record, rules, source):
    """Each field independently supplies candidate targets; agreement is intersection.

    complete: all three fields recognized, one common target.
    partial: one common target but missing/unmapped fields.
    unknown: no field recognized.
    conflict: disjoint candidates or more than one common target.
    Status describes mapping completeness, not partial allowance of an appeal.
    """
    validate_rules(rules)
    if not isinstance(record, dict):
        raise ValueError("Each record must be an object")
    if not isinstance(source, dict) or not source:
        raise ValueError("Input provenance is required")
    evidence, candidates, unmatched = [], [], []
    for field in FIELDS:
        value = record.get(field)
        matches = [
            rule
            for rule in rules["rules"]
            if field in rule["match"] and canonical(value) == canonical(rule["match"][field])
        ]
        if not matches:
            unmatched.append(field)
            continue
        candidates.append({rule["target"] for rule in matches})
        for rule in sorted(matches, key=lambda item: item["id"]):
            evidence.append(
                {
                    "field": field,
                    "value": value,
                    "rule_id": rule["id"],
                    "target": rule["target"],
                    "references": rule["evidence"],
                }
            )
    common = set.intersection(*candidates) if candidates else set()
    status = (
        "unknown"
        if not candidates
        else "conflict"
        if len(common) != 1
        else "partial"
        if unmatched
        else "complete"
    )
    return {
        "input": record,
        "status": status,
        "target": next(iter(common)) if len(common) == 1 else None,
        "candidates": sorted(set.union(*candidates)) if candidates else [],
        "unmatched_fields": unmatched,
        "rule_version": rules["rule_version"],
        "rules_sha256": hashlib.sha256(canonical(rules).encode()).hexdigest(),
        "evidence": {"input": source, "matches": evidence},
    }
