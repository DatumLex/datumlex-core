"""Read-only projection and receipts for a single cell of a civil cohort."""

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone

from src.accounts.models import Court
from src.db.civil_subjects import CATALOG, ROOT, branch_codes
from src.db.court_catalog import ACTIVE_COURTS
from src.db.models import (
    DimClass, DimDegree, DimOrg, DimProcess, DimResult, DimSubject, DimTime,
    ExtractionRun, FactProcess, FactProcessSubject, ProcessMovement,
)
from src.db.sampling_models import CivilSampleMember, CivilSamplingCohort
from src.services.corpus_catalog import CATEGORIES, safe_url
from src.services.outcomes import CODES, VERSION, classify_movements

SCHEMA_VERSION = 1
FACT_DEPENDENCIES = {
    "process_dimension_id": DimProcess, "time_id": DimTime, "process_class_id": DimClass,
    "degree_dimension_id": DimDegree, "result_id": DimResult, "organization_id": DimOrg,
    "last_run_id": ExtractionRun,
}


def json_date(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Unsupported manifest value: {type(value).__name__}")


def canonical_bytes(value):
    return json.dumps(
        value, default=json_date, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def is_sha256(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def read_rows(query, *, omit=()):
    fields = [field.attname for field in query.model._meta.concrete_fields if field.attname not in omit]
    key = query.model._meta.pk.attname
    return {row[key]: row for row in query.order_by("pk").values(*fields)}


def read_cell(name, court, year, *, using="default"):
    cohort = CivilSamplingCohort.objects.using(using).get(name=name)
    query = CivilSampleMember.objects.using(using).filter(cohort=cohort, court=court, year=year)
    return read_selection(cohort, query, using=using, courts=(court,))


def read_cohort(name, *, using="default"):
    cohort = CivilSamplingCohort.objects.using(using).get(name=name)
    return read_selection(cohort, CivilSampleMember.objects.using(using).filter(cohort=cohort), using=using)


def read_selection(cohort, query, *, using, courts=None):
    members = read_rows(query)
    if courts is None:
        courts = {row["court"] for row in members.values()}
    facts = read_rows(FactProcess.objects.using(using).filter(pk__in={row["fact_id"] for row in members.values()}),
                      omit=("raw_payload",))
    subjects = read_rows(FactProcessSubject.objects.using(using).filter(process_id__in=facts))
    tables = {
        "warehouse_civilsamplingcohort": read_rows(CivilSamplingCohort.objects.using(using).filter(pk=cohort.pk)),
        "warehouse_civilsamplemember": members,
        "fact_resource": facts,
        "fact_process_subject": subjects,
        "dim_subject": read_rows(DimSubject.objects.using(using).filter(pk__in={row["subject_id"] for row in subjects.values()})),
        "accounts_court": read_rows(Court.objects.using(using).filter(code__in=courts)),
    }
    for key, model in FACT_DEPENDENCIES.items():
        ids = {row[key] for row in facts.values()}
        if model is DimProcess:
            ids.update(row["process_id"] for row in members.values())
        tables[model._meta.db_table] = read_rows(model.objects.using(using).filter(pk__in=ids), omit=("cursor", "error"))
    movements = defaultdict(list)
    for movement in ProcessMovement.objects.using(using).filter(process_id__in=facts, code__in=CODES, occurred_at__isnull=False).only(
        "id", "process_id", "code", "occurred_at", "fingerprint",
    ).order_by("pk"):
        movements[movement.process_id].append(movement)
    return cohort.definition, tables, movements


def validate_cell(tables, movements, court, start, end, codes):
    members = tables["warehouse_civilsamplemember"]
    facts = tables["fact_resource"]
    subjects = defaultdict(set)
    broken_subjects = set()
    errors = Counter()
    for row in tables["fact_process_subject"].values():
        subject = tables["dim_subject"].get(row["subject_id"])
        if subject is None or row["process_id"] not in facts:
            errors["subject_dependency"] += 1
            broken_subjects.add(row["process_id"])
        elif subject["code"] in subjects[row["process_id"]]:
            errors["duplicate_subject"] += 1
        else:
            subjects[row["process_id"]].add(subject["code"])

    duplicates = [Counter() for _ in range(3)]
    for member in members.values():
        fact = facts.get(member["fact_id"])
        process = tables["dim_process"].get(member["process_id"])
        if fact and process:
            for counts, value in zip(duplicates, (fact["id"], fact["source_id"], process["number_process"])):
                counts[value] += 1

    suspensions = {}
    proofs = {}
    outcomes = Counter()
    series = Counter()
    eligibility = Counter()
    for member_id, member in members.items():
        fact = facts.get(member["fact_id"])
        reasons = []
        if not fact or member["cohort_id"] not in tables["warehouse_civilsamplingcohort"]:
            suspensions[member_id] = ["member_dependency"]
            continue
        dependencies = {key: tables[model._meta.db_table].get(fact[key]) for key, model in FACT_DEPENDENCIES.items()}
        if (not all(dependencies.values()) or fact["process_dimension_id"] != member["process_id"]
                or fact["id"] in broken_subjects):
            suspensions[member_id] = ["fact_dependency"]
            continue
        process = dependencies["process_dimension_id"]
        filing = dependencies["time_id"]
        organization = dependencies["organization_id"]
        degree = dependencies["degree_dimension_id"]["code"]
        number = process["number_process"]
        if any(counts[value] > 1 for counts, value in zip(duplicates, (fact["id"], fact["source_id"], number))):
            reasons.append("duplicate_member")
        if (member["court"] != court or fact["court"] != court or organization["court"] != court
                or not any(row["code"] == court for row in tables["accounts_court"].values())):
            reasons.append("court")
        if (not start <= filing["date"] <= end or member["year"] != filing["date"].year
                or filing["year"] != filing["date"].year or member["filing_month"] != filing["date"].month
                or filing["month"] != filing["date"].month or filing["quarter"] != (filing["date"].month - 1) // 3 + 1):
            reasons.append("filing_period")
        if process["secrecy_level"] != 0 or not re.fullmatch(r"[0-9]{20}", number):
            reasons.append("public_process")
        if member["subject_code"] not in subjects[fact["id"]] & codes:
            reasons.append("subject")
        if not is_sha256(fact["payload_hash"]) or not fact["source_id"] or fact["quant_process"] != 1:
            reasons.append("fact_provenance")
        if reasons:
            suspensions[member_id] = reasons
            continue

        result = classify_movements(court, degree, movements.get(fact["id"], ()))
        actual = result["outcome"]
        stored = dependencies["result_id"]["name"]
        if actual != ("outside_appellate_degree" if stored == "outside_degree" else stored):
            errors["outcome_mismatch"] += 1
        outcomes[actual] += 1
        series[(filing["quarter"], degree)] += 1
        eligibility["eligible"] += 1
        if actual != "outside_appellate_degree" and result["selected_evidence"]:
            selected = result["selected_evidence"][0]
            candidates = {item["movement_id"] for item in result["evidence"]}
            movement = next(row for row in movements[fact["id"]] if row.pk == selected["movement_id"])
            if not is_sha256(movement.fingerprint):
                errors["movement_provenance"] += 1
            if any(row.pk != movement.pk and row.occurred_at == movement.occurred_at
                   and row.code != movement.code and row.pk in candidates
                   for row in movements[fact["id"]]):
                eligibility["outcome_ties"] += 1
            proofs[fact["id"]] = {**selected, "fingerprint": movement.fingerprint}
    return {
        "errors": dict(errors), "suspensions": suspensions, "eligible": eligibility["eligible"],
        "outcome_ties": eligibility["outcome_ties"], "proofs": proofs,
        "indicators": {
            "outcomes": dict(outcomes), "binary_denominator": outcomes["granted"] + outcomes["denied"],
            "series": [{"quarter": q, "degree": d, "count": n} for (q, d), n in sorted(series.items())],
        },
    }


def collection_rows(collection, key, errors):
    rows = collection.get(key)
    if not isinstance(rows, list):
        errors["collection_structure"] += 1
        return {}
    indexed = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] or row["id"] in indexed:
            errors["collection_identity"] += 1
        else:
            indexed[row["id"]] = row
    return indexed


def approved_source(row):
    return (row.get("review_status") == "approved" and safe_url(row.get("source_url"))
            and isinstance(row.get("source_locator"), str) and row["source_locator"].strip())


def validate_collection(collection, codes):
    if collection is None:
        return None, {}
    errors = Counter()
    if (not isinstance(collection, dict) or not isinstance(collection.get("id"), str) or not collection["id"]
            or not isinstance(collection.get("version"), str) or not collection["version"]
            or type(collection.get("synthetic")) is not bool):
        return None, {"collection_structure": 1}

    items = collection_rows(collection, "items", errors)
    references = collection_rows(collection, "references", errors)
    versions = collection_rows(collection, "text_versions", errors)
    evidence = collection_rows(collection, "evidence", errors)
    categories = Counter()
    linked_versions, linked_references, published_evidence = set(), set(), set()
    for item in items.values():
        category = item.get("category")
        if category not in CATEGORIES or not approved_source(item):
            errors["source_approval"] += 1
        else:
            categories[category] += 1
        item_codes = item.get("subject_codes")
        required = item.get("tpu_required")
        valid_codes = (isinstance(item_codes, list) and all(type(code) is int for code in item_codes)
                       and len(item_codes) == len(set(item_codes)))
        if type(required) is not bool or not valid_codes or (required and not codes.intersection(item_codes)):
            errors["source_tpu"] += 1

        reference_id = item.get("reference_id")
        if reference_id is not None or category in ("precedent", "doctrine"):
            reference = references.get(reference_id) if isinstance(reference_id, str) else None
            if not reference or reference.get("category") != category or not approved_source(reference):
                errors["source_reference"] += 1
            else:
                linked_references.add(reference_id)

        version_id = item.get("text_version_id")
        version = versions.get(version_id) if isinstance(version_id, str) else None
        if version_id is not None:
            if (not version or version.get("item_id") != item["id"] or version.get("rights") != "authorized"
                    or not approved_source(version) or version.get("source_url") != item.get("source_url")):
                errors["text_provenance"] += 1
            else:
                linked_versions.add(version_id)
                if required and version.get("subject_codes") != sorted(item_codes if valid_codes else []):
                    errors["text_tpu"] += 1

        evidence_ids = item.get("evidence_ids")
        if (not isinstance(evidence_ids, list) or not all(isinstance(key, str) for key in evidence_ids)
                or len(set(evidence_ids)) != len(evidence_ids)):
            errors["evidence_reference"] += 1
            continue
        for key in evidence_ids:
            row = evidence.get(key)
            if not version or not row or row.get("text_version_id") != version_id or row.get("review_status") != "approved":
                errors["evidence_reference"] += 1
            else:
                published_evidence.add(key)

    for version in versions.values():
        text = version.get("text")
        if not isinstance(text, str) or hashlib.sha256(text.encode("utf-8")).hexdigest() != version.get("sha256"):
            errors["text_hash"] += 1
    review_counts = Counter()
    for row in evidence.values():
        status = row.get("review_status")
        if status not in ("candidate", "approved", "rejected", "withdrawn"):
            errors["evidence_review"] += 1
        else:
            review_counts[status] += 1
        version_id = row.get("text_version_id")
        version = versions.get(version_id) if isinstance(version_id, str) else None
        text = version.get("text") if version else None
        start, end = row.get("start"), row.get("end")
        if (not isinstance(text, str) or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(text) or row.get("text_sha256") != version.get("sha256")
                or hashlib.sha256(text[start:end].encode("utf-8")).hexdigest() != row.get("excerpt_sha256")
                or not isinstance(row.get("rule_version"), str) or not row["rule_version"].strip()):
            errors["evidence_provenance"] += 1

    if set(versions) != linked_versions or set(references) != linked_references:
        errors["collection_dependency"] += 1
    normalized = {key: sorted(rows.values(), key=lambda row: row["id"]) for key, rows in (
        ("items", items), ("references", references), ("text_versions", versions), ("evidence", evidence),
    )}
    summary = {
        "id": collection["id"], "version": collection["version"], "synthetic": collection["synthetic"],
        "categories": {category: categories[category] for category in CATEGORIES},
        "references": len(references), "text_versions": len(versions), "evidence_review": dict(review_counts),
        "selected_evidence": len(published_evidence), "sha256": digest(normalized),
    }
    return summary, dict(errors)


def cohort_codes(definition, year):
    official = branch_codes(ROOT)
    configured = definition.get("subjects")
    target = definition.get("target")
    if (not isinstance(configured, list) or not configured or not all(type(code) is int for code in configured)
            or not set(configured) <= official or definition.get("sgt_version") != CATALOG["version"]
            or type(target) is not int or target < 1 or type(definition.get("start_year")) is not int
            or year < definition["start_year"] or not isinstance(definition.get("seed"), str) or not definition["seed"]):
        raise ValueError("Definição da coorte ou versão TPU incompatível.")
    return set(configured)


def build_manifest(name, court, year, definition, tables, movements, collection=None, *, through=None):
    start, end = date(year, 1, 1), through or date(year, 12, 31)
    codes = cohort_codes(definition, year)
    target = definition["target"]
    result = validate_cell(tables, movements, court, start, end, codes)
    legal, legal_errors = validate_collection(collection, branch_codes(ROOT))
    errors = {**result["errors"], **legal_errors}
    count = len(tables["warehouse_civilsamplemember"])
    if count > target:
        errors["target_exceeded"] = 1
    if count == 0:
        errors["empty_cell"] = 1
    valid = not errors and not result["suspensions"]

    projection = {key: [row for _, row in sorted(rows.items())] for key, rows in tables.items()}
    projection["outcome_proof"] = [{"fact_id": fact_id, **proof} for fact_id, proof in sorted(result["proofs"].items())]
    scope = {"cohort": name, "court": court, "start": start.isoformat(), "end": end.isoformat(), "year": year}
    table_receipts = {key: {"rows": len(rows), "sha256": digest(rows)} for key, rows in projection.items()}
    snapshot = {
        "scope": scope, "tables": table_receipts, "outcome_rule": VERSION,
        "collection_sha256": legal["sha256"] if legal else None,
    }
    reasons = ["coverage_unverified"]
    if count < target:
        reasons.append("partial_cell")
    if not valid:
        reasons.append("validation_failed")
    if legal and legal["synthetic"]:
        reasons.append("synthetic_collection")
    suspensions = Counter(reason for flags in result["suspensions"].values() for reason in flags)
    snapshot_sha256 = digest(snapshot)
    body = {
        "schema_version": SCHEMA_VERSION,
        "mode": "dry_run",
        "publication_version": f"sha256:{snapshot_sha256}",
        "scope": scope,
        "selection": {"tpu_root": ROOT, "sgt_version": CATALOG["version"], "codes": sorted(codes),
                      "seed": definition["seed"], "grain": "CNJ/tribunal/ano", "source": "stored_cohort_membership"},
        "coverage": {"state": "partial" if count < target else "unverified",
                     "target": target, "selected": count, "gap": max(0, target - count), "source_exhaustion": "unverified"},
        "dependencies": {**{key: model._meta.db_table for key, model in FACT_DEPENDENCIES.items()},
                         "member": ["warehouse_civilsamplingcohort", "fact_resource", "dim_process"],
                         "subject_link": ["fact_resource", "dim_subject"], "outcome_proof": ["fact_resource"],
                         "court_access": "accounts_court"},
        "provenance": {"source": "local_postgresql", "raw_payload": "retained_in_source",
                       "last_collection": max((row["collected_at"] for row in tables["fact_resource"].values()), default=None),
                       "canonical_format": "UTF-8 JSON, sorted keys, compact, UTC ISO timestamps; SHA-256"},
        "indicators": {**result["indicators"], "eligible": result["eligible"], "rule_version": VERSION,
                       "tie_break": "latest_occurred_at_then_highest_original_movement_id",
                       "distinct_numbers": len({row["number_process"] for row in tables["dim_process"].values()}),
                       "outcome_ties": result["outcome_ties"]},
        "validation": {"status": "passed" if valid else "failed", "errors": errors,
                       "suspended_members": len(result["suspensions"]), "suspension_reasons": dict(suspensions)},
        "collection": legal,
        "snapshot": {**snapshot, "sha256": snapshot_sha256},
        "publication": {"status": "blocked", "reasons": reasons},
    }
    return {"manifest": body, "sha256": digest(body)}


def load_revocations(path):
    if path is None:
        return None
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, list) or not all(isinstance(value, str) and re.fullmatch(r"[0-9]{20}", value)
                                               for value in values):
        raise ValueError("Lista local de revogações inválida.")
    return frozenset(values)


def build_cohort_manifest(name, through, definition, tables, movements, revoked=None):
    """Validate membership per cell and hash the union of its projected rows once."""
    codes = cohort_codes(definition, through.year)
    amount = definition["target"]
    start_year = definition["start_year"]
    cells = {(court, year): {} for court in sorted(ACTIVE_COURTS) for year in range(start_year, through.year + 1)}
    by_fact = defaultdict(dict)
    for key, link in tables["fact_process_subject"].items():
        by_fact[link["process_id"]][key] = link
    members = tables["warehouse_civilsamplemember"]
    facts = tables["fact_resource"]
    processes = tables["dim_process"]
    suspensions = Counter()
    revoked_members = set()
    for key, member in members.items():
        cell = cells.get((member["court"], member["year"]))
        if cell is None:
            suspensions["outside_scope"] += 1
            continue
        cell[key] = member
        process = processes.get(member["process_id"])
        if revoked is not None and process and process["number_process"] in revoked:
            revoked_members.add(key)
    suspensions["revoked"] = len(revoked_members)

    errors, outcomes = Counter(), Counter()
    proofs, coverage, series = {}, [], []
    eligible, ties, suspended = 0, 0, suspensions["outside_scope"]
    for (court, year), selection in cells.items():
        count = len(selection)
        accepted = unavailable = 0
        if count:
            ids = {member["fact_id"] for member in selection.values()}
            projected = {
                **tables, "warehouse_civilsamplemember": selection,
                "fact_resource": {key: facts[key] for key in ids if key in facts},
                "fact_process_subject": {key: row for fact in ids for key, row in by_fact[fact].items()},
            }
            result = validate_cell(projected, movements, court, date(year, 1, 1),
                                   min(through, date(year, 12, 31)), codes)
            revoked_keys = selection.keys() & revoked_members
            accepted = result["eligible"] - len(revoked_keys - result["suspensions"].keys())
            unavailable = len(result["suspensions"].keys() | revoked_keys)
            eligible += accepted
            suspended += unavailable
            errors.update(result["errors"])
            suspensions.update(reason for reasons in result["suspensions"].values() for reason in reasons)
            outcomes.update(result["indicators"]["outcomes"])
            series.extend({**row, "court": court, "year": year} for row in result["indicators"]["series"])
            ties += result["outcome_ties"]
            proofs.update(result["proofs"])
        if count > amount:
            errors["target_exceeded"] += 1
        coverage.append({
            "court": court, "year": year, "members": count, "eligible": accepted, "suspended": unavailable,
            "target": amount, "gap": max(0, amount - accepted), "source_exhaustion": "unverified",
            "state": "unverified" if not count else "partial" if accepted < amount else "target_met",
        })
    if not members:
        errors["empty_cohort"] += 1
    if set(facts) != {row["fact_id"] for row in members.values()}:
        errors["fact_membership"] += 1
    if set(by_fact) - set(facts):
        errors["subject_dependency"] += 1
    valid = not errors and not suspended
    scope = {"kind": "cohort", "cohort": name, "start": date(start_year, 1, 1).isoformat(),
             "end": through.isoformat(), "courts": sorted(ACTIVE_COURTS)}
    projection = {key: [row for _, row in sorted(rows.items())] for key, rows in tables.items()}
    projection["outcome_proof"] = [{"fact_id": key, **proof} for key, proof in sorted(proofs.items())]
    snapshot = {"scope": scope, "outcome_rule": VERSION, "collection_sha256": None, "tables": {
        key: {"rows": len(rows), "sha256": digest(rows)} for key, rows in projection.items()
    }}
    snapshot_sha = digest(snapshot)
    gap = sum(cell["gap"] for cell in coverage)
    receipt = {
        "schema_version": SCHEMA_VERSION, "mode": "dry_run", "scope": scope,
        "publication_version": f"sha256:{snapshot_sha}",
        "selection": {"tpu_root": ROOT, "sgt_version": CATALOG["version"], "codes": sorted(codes),
                      "seed": definition["seed"], "grain": "CNJ/tribunal/ano", "source": "stored_cohort_membership"},
        "coverage": {"target": amount * len(cells), "gap": gap, "cells": coverage,
                     "observed_cells": len({(row["court"], row["year"]) for row in members.values()} & cells.keys())},
        "counts": {"members": len(members), "facts": len(facts),
                   "distinct_cnj": len({row["number_process"] for row in processes.values()}),
                   "cell_occurrences": len({(row["court"], row["year"], row["process_id"]) for row in members.values()})},
        "indicators": {"outcomes": dict(sorted(outcomes.items())), "outcome_ties": ties,
                       "binary_denominator": outcomes["granted"] + outcomes["denied"], "series": series,
                       "rule_version": VERSION, "tie_break": "latest_occurred_at_then_highest_original_movement_id"},
        "validation": {"status": "passed" if valid else "failed", "errors": dict(errors),
                       "eligible_members": eligible, "suspended_members": suspended,
                       "suspension_reasons": {key: value for key, value in suspensions.items() if value},
                       "revocations": {"provided": revoked is not None, "entries": len(revoked or ())}},
        "provenance": {"source": "local_postgresql", "raw_payload": "retained_in_source",
                       "local_scope_only": True, "canonical_format": "UTF-8 sorted compact JSON; SHA-256"},
        "dependencies": {**{key: model._meta.db_table for key, model in FACT_DEPENDENCIES.items()},
                         "member": ["warehouse_civilsamplingcohort", "fact_resource", "dim_process"],
                         "subject_link": ["fact_resource", "dim_subject"], "outcome_proof": ["fact_resource"]},
        "collection": None,
        "snapshot": {**snapshot, "sha256": snapshot_sha},
        "publication": {"status": "blocked", "reasons": ["coverage_unverified",
                        *(["partial_cohort"] if gap else []), *(["validation_failed"] if not valid else [])]},
    }
    return {"manifest": receipt, "sha256": digest(receipt)}, proofs


def verify_rollback(current, previous, expected_digest):
    """Check the restored projection against a separately retained receipt hash."""
    if not isinstance(previous, dict) or not isinstance(previous.get("manifest"), dict):
        return False
    body = previous["manifest"]
    current_body = current["manifest"]
    snapshot = body.get("snapshot")
    return (
        is_sha256(expected_digest) and expected_digest == previous.get("sha256") == digest(body)
        and body.get("schema_version") == SCHEMA_VERSION and isinstance(snapshot, dict)
        and body.get("validation") == current_body["validation"]
        and current_body["validation"]["status"] == "passed"
        and body.get("scope") == current_body["scope"] and snapshot == current_body["snapshot"]
    )
