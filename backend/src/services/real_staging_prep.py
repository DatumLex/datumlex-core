"""Selective, minimized, fail-closed staging builder for real DataJud procedural records.

Copies ONLY the minimal procedural tables and fields required for individual search,
CNJ lookup, filtering, pagination, case details, merit outcome indicators, and exports
from the local operational database (`datumlex_ops_f3_full`) into a separate, local,
private staging PostgreSQL database (`datumlex_staging_*`).

Strictly excludes accounts, password hashes, sessions, user audit logs, secrets,
NLP history/evidence, and all legal corpus/reference sources. Never modifies the source
database and never prints or exports credentials or CNJs into audit manifests.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from django.conf import settings
from django.db import connections, transaction
from django.db.models import Count
from django.utils import timezone

from src.accounts.models import AuditEvent, Court, RequestLimit, SupportIdentity, User
from src.db.models import (
    CrossSourceLinkCandidate,
    DimClass,
    DimDegree,
    DimOrg,
    DimProcess,
    DimResult,
    DimSubject,
    DimTime,
    ExtractionRun,
    FactProcess,
    FactProcessSubject,
    LegalCorpusItem,
    LegalCorpusTopicMatch,
    LegalNarrativeDraft,
    LegalReference,
    NlpDocument,
    NlpEvidence,
    NlpExtraction,
    NlpRevision,
    NlpSnapshot,
    NlpSourceObservation,
    NlpTextVersion,
    ProcessMovement,
    RejectedRecord,
)
from src.db.sampling_models import CivilSampleMember, CivilSamplingCohort
from src.services.outcomes import CODES as OUTCOME_CODES

EXPECTED_SOURCE_DATABASE = "datumlex_ops_f3_full"
EXPECTED_COHORT = "civil-2010-sgt-2026-11"
STAGING_DB_RE = re.compile(r"^datumlex_staging_[a-z0-9_]+$")
CNJ_RE = re.compile(r"^[0-9]{20}$")
LOCAL_HOSTS = ("", "localhost", "127.0.0.1", "::1")
ADVISORY_LOCK_KEY = 2411222035
REMOTE_ENV_MARKERS = (
    "RAILWAY_ENVIRONMENT_NAME",
    "RAILWAY_SERVICE_NAME",
    "RAILWAY_PROJECT_ID",
    "VERCEL",
    "VERCEL_ENV",
    "RENDER",
    "RENDER_EXTERNAL_HOSTNAME",
)
ALLOWED_RUN_SCOPE_KEYS = frozenset(
    {
        "court",
        "start",
        "end",
        "end_exclusive",
        "origin",
        "period_field",
        "cohort",
        "year",
        "page_size",
        "subject_policy",
        "coverage",
    }
)
RESULT_SEED_NAMES = frozenset(
    {"denied", "unknown", "partial_knowledge", "not_admitted", "partial", "granted", "outside_degree"}
)

INCLUDED_MODELS = (
    Court,
    DimProcess,
    DimTime,
    DimClass,
    DimDegree,
    DimResult,
    DimOrg,
    ExtractionRun,
    DimSubject,
    CivilSamplingCohort,
    FactProcess,
    FactProcessSubject,
    CivilSampleMember,
    ProcessMovement,
)

EXCLUDED_MODELS = (
    User,
    SupportIdentity,
    AuditEvent,
    RequestLimit,
    LegalReference,
    LegalCorpusItem,
    LegalCorpusTopicMatch,
    LegalNarrativeDraft,
    CrossSourceLinkCandidate,
    RejectedRecord,
    NlpSnapshot,
    NlpDocument,
    NlpTextVersion,
    NlpExtraction,
    NlpEvidence,
    NlpRevision,
    NlpSourceObservation,
)


class StagingPrepError(ValueError):
    """Raised when any environment, secrecy, minimization, or integrity guard fails."""


def sanitize_extraction_scope(scope: Any) -> dict[str, Any]:
    """Strip internal backup/snapshot names and oversized lists from ExtractionRun.scope."""
    if not isinstance(scope, dict):
        return {}
    return {k: v for k, v in scope.items() if k in ALLOWED_RUN_SCOPE_KEYS}


def assert_safe_staging_databases(
    source_alias: str,
    target_alias: str,
    *,
    allow_test_db: bool = False,
) -> tuple[str, str]:
    """Ensure source is local operational DB and target is a distinct local staging DB."""
    if getattr(settings, "SYNTHETIC_PREVIEW", False):
        raise StagingPrepError("Operação bloqueada: SYNTHETIC_PREVIEW está ativo.")
    for marker in REMOTE_ENV_MARKERS:
        if os.environ.get(marker):
            raise StagingPrepError(f"Operação bloqueada em ambiente remoto ({marker} presente).")
    if source_alias == target_alias:
        raise StagingPrepError("Origem e destino não podem usar o mesmo alias de banco.")
    if source_alias not in connections or target_alias not in connections:
        raise StagingPrepError("Alias de banco de origem ou destino não configurado.")

    src = connections[source_alias]
    dst = connections[target_alias]
    src_name = str(src.settings_dict.get("NAME", ""))
    dst_name = str(dst.settings_dict.get("NAME", ""))

    if allow_test_db:
        return src_name, dst_name

    if src.vendor != "postgresql" or dst.vendor != "postgresql":
        raise StagingPrepError("Origem e destino devem usar PostgreSQL local.")
    if src.settings_dict.get("HOST", "") not in LOCAL_HOSTS or dst.settings_dict.get("HOST", "") not in LOCAL_HOSTS:
        raise StagingPrepError("Origem e destino devem estar em loopback local (127.0.0.1/localhost).")
    if src_name != EXPECTED_SOURCE_DATABASE:
        raise StagingPrepError(f"Banco de origem inesperado ({src_name!r}); esperado {EXPECTED_SOURCE_DATABASE!r}.")
    if dst_name == EXPECTED_SOURCE_DATABASE:
        raise StagingPrepError("Recusado: destino nunca pode ser o banco operacional.")
    if not STAGING_DB_RE.fullmatch(dst_name):
        raise StagingPrepError(
            f"Nome do banco intermediário ({dst_name!r}) deve obedecer ao prefixo 'datumlex_staging_*'."
        )
    return src_name, dst_name


def _read_rows(model, qs, *, omit: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    fields = [f.attname for f in model._meta.concrete_fields if f.attname not in omit]
    return list(qs.order_by("pk").values(*fields))


def _insert_rows(db, cursor, model, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    fields = model._meta.concrete_fields
    quote = db.ops.quote_name
    table = quote(model._meta.db_table)
    columns = ", ".join(quote(f.column) for f in fields)
    placeholders = ", ".join("%s" for _ in fields)
    pk_col = quote(model._meta.pk.column)
    stmt = f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) ON CONFLICT ({pk_col}) DO NOTHING"
    payload = [tuple(f.get_db_prep_save(row[f.attname], db) for f in fields) for row in rows]
    cursor.executemany(stmt, payload)
    inserted = cursor.rowcount
    if db.vendor == "postgresql" and model._meta.pk.get_internal_type() in (
        "AutoField",
        "BigAutoField",
        "SmallAutoField",
    ):
        cursor.execute("SELECT pg_get_serial_sequence(%s, %s)", (model._meta.db_table, model._meta.pk.column))
        seq = cursor.fetchone()[0]
        if seq:
            cursor.execute(f"SELECT COALESCE(MAX({pk_col}), 0) + 1 FROM {table}")
            nxt = int(cursor.fetchone()[0])
            ident = ".".join(quote(part) for part in seq.split("."))
            cursor.execute(f"ALTER SEQUENCE {ident} RESTART WITH {nxt}")
    return inserted


def _compute_dataset_digest(alias: str, cohort_name: str) -> dict[str, Any]:
    """Compute privacy-safe summary counts and deterministic SHA-256 digest (zero CNJs)."""
    member_fact_ids = CivilSampleMember.objects.using(alias).filter(
        cohort__name=cohort_name
    ).values_list("fact_id", flat=True)
    facts = FactProcess.objects.using(alias).filter(pk__in=member_fact_ids)

    table_counts = {m._meta.db_table: m.objects.using(alias).count() for m in INCLUDED_MODELS}
    excluded_counts = {m._meta.db_table: m.objects.using(alias).count() for m in EXCLUDED_MODELS}
    with connections[alias].cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM django_session")
        excluded_counts["django_session"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM accounts_user_courts")
        excluded_counts["accounts_user_courts"] = cur.fetchone()[0]

    per_court = {}
    for row in facts.values("court").annotate(
        documents=Count("pk", distinct=True),
        distinct_cnjs=Count("process_dimension_id", distinct=True),
    ).order_by("court"):
        per_court[row["court"]] = {
            "documents": row["documents"],
            "distinct_cnjs": row["distinct_cnjs"],
        }

    outcomes = {
        row["result__name"]: row["n"]
        for row in facts.values("result__name").annotate(n=Count("pk", distinct=True)).order_by("result__name")
    }
    granted = outcomes.get("granted", 0)
    denied = outcomes.get("denied", 0)
    binary_denominator = granted + denied

    # Deterministic order-independent digest over (fact.pk, fact.court, fact.payload_hash, result.name)
    # Uses payload_hash (SHA-256) rather than raw CNJs so zero PII is serialized.
    fact_fingerprints = list(
        facts.order_by("pk").values_list("pk", "court", "payload_hash", "result__name", "degree_dimension__code")
    )
    canonical = json.dumps(
        {
            "cohort": cohort_name,
            "table_counts": table_counts,
            "per_court": per_court,
            "outcomes": outcomes,
            "fact_fingerprints": fact_fingerprints,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return {
        "cohort": cohort_name,
        "table_counts": table_counts,
        "excluded_table_counts": excluded_counts,
        "total_documents": facts.count(),
        "total_distinct_cnjs": facts.values("process_dimension_id").distinct().count(),
        "per_court": per_court,
        "outcomes": outcomes,
        "merit_binary": {
            "eligible": binary_denominator,
            "granted": granted,
            "denied": denied,
            "grant_rate": round(granted / binary_denominator, 6) if binary_denominator else None,
        },
        "canonical_sha256": hashlib.sha256(canonical).hexdigest(),
    }


def audit_staging_database(
    alias: str,
    *,
    cohort_name: str = EXPECTED_COHORT,
) -> dict[str, Any]:
    """Read-only verification of exclusion, secrecy, minimization, and integrity invariants."""
    db = connections[alias]
    with transaction.atomic(using=alias, durable=False):
        if db.vendor == "postgresql":
            with db.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        summary = _compute_dataset_digest(alias, cohort_name)

        nonempty_excluded = {k: v for k, v in summary["excluded_table_counts"].items() if v != 0}
        if nonempty_excluded:
            raise StagingPrepError(f"Tabelas excluídas contêm registros no destino: {nonempty_excluded}")

        secrecy_violations = DimProcess.objects.using(alias).exclude(secrecy_level=0).count()
        if secrecy_violations:
            raise StagingPrepError(f"Encontrados {secrecy_violations} processos com secrecy_level != 0.")

        nonempty_raw = FactProcess.objects.using(alias).exclude(raw_payload={}).count()
        if nonempty_raw:
            raise StagingPrepError(f"Encontrados {nonempty_raw} registros com raw_payload não vazio.")

        nonempty_complements = ProcessMovement.objects.using(alias).exclude(complements=[]).count()
        nonempty_mv_names = ProcessMovement.objects.using(alias).exclude(name="").count()
        if nonempty_complements or nonempty_mv_names:
            raise StagingPrepError("ProcessMovement contém complements ou name não minimizados.")

        dirty_runs = (
            ExtractionRun.objects.using(alias).exclude(cursor=None).count()
            + ExtractionRun.objects.using(alias).exclude(error="").count()
        )
        if dirty_runs:
            raise StagingPrepError("ExtractionRun contém cursor ou error não minimizados.")

    return {
        **summary,
        "invariants": {
            "all_excluded_tables_zero": True,
            "secrecy_level_zero_only": True,
            "raw_payload_minimized": True,
            "movements_minimized": True,
            "extraction_runs_minimized": True,
        },
    }


def materialize_minimized_staging(
    source_alias: str,
    target_alias: str,
    *,
    cohort_name: str = EXPECTED_COHORT,
    allow_test_db: bool = False,
) -> dict[str, Any]:
    """Copy a minimized, sanitized procedural projection from source to local staging DB."""
    src_name, dst_name = assert_safe_staging_databases(
        source_alias, target_alias, allow_test_db=allow_test_db
    )
    src_db = connections[source_alias]
    dst_db = connections[target_alias]

    # 1. Read strictly READ ONLY from source
    with transaction.atomic(using=source_alias, durable=not allow_test_db):
        if src_db.vendor == "postgresql":
            with src_db.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                cur.execute("SELECT current_database(), current_setting('transaction_read_only')")
                if cur.fetchone() != (src_name, "on"):
                    raise StagingPrepError("Origem não confirmou banco esperado ou modo READ ONLY.")

        cohort = CivilSamplingCohort.objects.using(source_alias).filter(name=cohort_name).first()
        if cohort is None:
            raise StagingPrepError(f"Coorte {cohort_name!r} não encontrada na origem.")

        members = _read_rows(
            CivilSampleMember,
            CivilSampleMember.objects.using(source_alias).filter(cohort=cohort),
        )
        fact_ids = {row["fact_id"] for row in members}
        courts_used = {row["court"] for row in members}

        facts_raw = _read_rows(
            FactProcess,
            FactProcess.objects.using(source_alias).filter(pk__in=fact_ids),
            omit=("raw_payload",),
        )
        facts = [{**row, "raw_payload": {}} for row in facts_raw]

        proc_ids = {row["process_dimension_id"] for row in facts} | {row["process_id"] for row in members}
        processes = _read_rows(DimProcess, DimProcess.objects.using(source_alias).filter(pk__in=proc_ids))
        for proc in processes:
            if proc["secrecy_level"] != 0:
                raise StagingPrepError("Bloqueado: registro com secrecy_level != 0 detectado na origem.")
            if not CNJ_RE.fullmatch(proc["number_process"] or ""):
                raise StagingPrepError("Bloqueado: número CNJ fora do padrão de 20 dígitos detectado na origem.")

        fps_rows = _read_rows(
            FactProcessSubject,
            FactProcessSubject.objects.using(source_alias).filter(process_id__in=fact_ids),
        )
        subject_ids = {row["subject_id"] for row in fps_rows}
        run_ids = {row["last_run_id"] for row in facts}

        runs_raw = _read_rows(
            ExtractionRun,
            ExtractionRun.objects.using(source_alias).filter(pk__in=run_ids),
            omit=("cursor", "error"),
        )
        runs = [
            {
                **row,
                "scope": sanitize_extraction_scope(row["scope"]),
                "cursor": None,
                "error": "",
            }
            for row in runs_raw
        ]

        movements_raw = _read_rows(
            ProcessMovement,
            ProcessMovement.objects.using(source_alias).filter(
                process_id__in=fact_ids,
                code__in=OUTCOME_CODES,
                occurred_at__isnull=False,
            ),
            omit=("name", "complements"),
        )
        movements = [{**row, "name": "", "complements": []} for row in movements_raw]

        tables: dict[str, list[dict[str, Any]]] = {
            "accounts_court": _read_rows(Court, Court.objects.using(source_alias).filter(code__in=courts_used)),
            "dim_process": processes,
            "dim_time": _read_rows(
                DimTime, DimTime.objects.using(source_alias).filter(pk__in={r["time_id"] for r in facts})
            ),
            "dim_class": _read_rows(
                DimClass, DimClass.objects.using(source_alias).filter(pk__in={r["process_class_id"] for r in facts})
            ),
            "dim_degree": _read_rows(
                DimDegree,
                DimDegree.objects.using(source_alias).filter(pk__in={r["degree_dimension_id"] for r in facts}),
            ),
            "dim_result": _read_rows(
                DimResult, DimResult.objects.using(source_alias).filter(pk__in={r["result_id"] for r in facts})
            ),
            "dim_org": _read_rows(
                DimOrg, DimOrg.objects.using(source_alias).filter(pk__in={r["organization_id"] for r in facts})
            ),
            "extraction_run": runs,
            "dim_subject": _read_rows(
                DimSubject, DimSubject.objects.using(source_alias).filter(pk__in=subject_ids)
            ),
            "warehouse_civilsamplingcohort": _read_rows(
                CivilSamplingCohort, CivilSamplingCohort.objects.using(source_alias).filter(pk=cohort.pk)
            ),
            "fact_resource": facts,
            "fact_process_subject": fps_rows,
            "warehouse_civilsamplemember": members,
            "process_movement": movements,
        }
        source_digest = _compute_dataset_digest(source_alias, cohort_name)

    # 2. Write atomically into empty staging database
    with transaction.atomic(using=target_alias, durable=not allow_test_db), dst_db.cursor() as cur:
        if dst_db.vendor == "postgresql":
            cur.execute("SELECT current_database(), pg_try_advisory_xact_lock(%s)", (ADVISORY_LOCK_KEY,))
            actual_dst, locked = cur.fetchone()
            if actual_dst != dst_name or not locked:
                raise StagingPrepError("Banco intermediário não confirmado ou bloqueio indisponível.")

        if FactProcess.objects.using(target_alias).exists():
            raise StagingPrepError("Banco intermediário não está vazio (fact_resource já possui registros).")

        # Clear default migration seed rows in Court and DimResult so source IDs are preserved exactly
        if set(DimResult.objects.using(target_alias).values_list("name", flat=True)).issubset(RESULT_SEED_NAMES):
            DimResult.objects.using(target_alias).delete()
        Court.objects.using(target_alias).delete()

        inserted = {}
        for model in INCLUDED_MODELS:
            tbl = model._meta.db_table
            inserted[tbl] = _insert_rows(dst_db, cur, model, tables[tbl])

        if dst_db.vendor == "postgresql":
            cur.execute("SET CONSTRAINTS ALL IMMEDIATE")

    # 3. Verify integrity, exclusions, minimization, and exact digest parity against source
    target_audit = audit_staging_database(target_alias, cohort_name=cohort_name)
    if (
        target_audit["total_documents"] != source_digest["total_documents"]
        or target_audit["total_distinct_cnjs"] != source_digest["total_distinct_cnjs"]
        or target_audit["merit_binary"] != source_digest["merit_binary"]
        or target_audit["per_court"] != source_digest["per_court"]
    ):
        raise StagingPrepError("Paridade entre origem e banco intermediário falhou na conferência pós-cópia.")

    return {
        "schema_version": 1,
        "generated_at": timezone.localtime().isoformat(timespec="seconds"),
        "source_database": src_name,
        "staging_database": dst_name,
        "cohort": cohort_name,
        "publication_status": "blocked_pending_authorization",
        "inserted_counts": inserted,
        "source_summary": {
            "total_documents": source_digest["total_documents"],
            "total_distinct_cnjs": source_digest["total_distinct_cnjs"],
            "merit_binary": source_digest["merit_binary"],
            "canonical_sha256": source_digest["canonical_sha256"],
        },
        "staging_audit": target_audit,
        "included_tables": [m._meta.db_table for m in INCLUDED_MODELS],
        "excluded_tables": sorted(target_audit["excluded_table_counts"].keys()),
        "minimized_fields": {
            "fact_resource.raw_payload": "stripped to {}",
            "process_movement.complements": "stripped to []",
            "process_movement.name": "stripped to ''",
            "process_movement.rows": "restricted to mapped outcome-proof codes only",
            "extraction_run.cursor": "stripped to NULL",
            "extraction_run.error": "stripped to ''",
            "extraction_run.scope": "allowlisted keys only (local backup names removed)",
        },
    }


def write_private_manifest(path: Path, data: dict[str, Any]) -> str:
    """Persist manifest JSON with mode 0600 (never prints or writes CNJs/credentials)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if path.exists():
        path.unlink()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return hashlib.sha256(raw).hexdigest()
