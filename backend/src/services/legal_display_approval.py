"""Auditable, fail-closed local display-only approval for curated legal sources.

Supports only explicitly allowlisted local candidates (`TJDFT:ACORDAO:1955493`
and `SENADO:RIL:61:241:237`) on the isolated local operational database
`datumlex_ops_f3_full`. Never grants `text`, `nlp`, or `gemini`, never approves
without an explicit human decision record, and supports per-source rollback.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from src.db.models import FactProcess, LegalCorpusItem, LegalReference
from src.services.corpus_publication import allowed_versions, published_items, published_references

EXPECTED_DATABASE = "datumlex_ops_f3_full"
EXPECTED_ENVIRONMENT = f"local:{EXPECTED_DATABASE}"
LOCAL_HOSTS = ("", "localhost", "127.0.0.1", "::1")
ADVISORY_LOCK_KEY = 3045188
REMOTE_ENV_MARKERS = (
    "RAILWAY_ENVIRONMENT_NAME",
    "RAILWAY_SERVICE_NAME",
    "RAILWAY_PROJECT_ID",
    "VERCEL",
    "VERCEL_ENV",
    "RENDER",
    "RENDER_EXTERNAL_HOSTNAME",
)


class ApprovalError(ValueError):
    """Raised when any environment, authorization, integrity, or state guard fails."""


@dataclass(frozen=True)
class CandidateSpec:
    identifier: str
    category: str
    court: str
    source_name: str
    source_institution: str | None
    has_reference: bool
    expected_fingerprint: str
    expected_origin_key: str | None


ALLOWED_CANDIDATES: dict[str, CandidateSpec] = {
    "TJDFT:ACORDAO:1955493": CandidateSpec(
        identifier="TJDFT:ACORDAO:1955493",
        category="jurisprudence",
        court="TJDFT",
        source_name="TJDFT",
        source_institution=None,
        has_reference=False,
        expected_fingerprint="1398af2191aac16d0d3c838afc1f6252860e59d9ed0da1dcb2958fc7e2e2d585",
        expected_origin_key="nlp:TJDFT:84fb6897-7b95-41b0-af60-8b04a7fa3411",
    ),
    "SENADO:RIL:61:241:237": CandidateSpec(
        identifier="SENADO:RIL:61:241:237",
        category="doctrine",
        court="",
        source_name="Senado Federal",
        source_institution="Senado",
        has_reference=True,
        expected_fingerprint="15b8358a2f086c86628de367f294c76ab1c479435fa78d6d81bb2a4cfb5e626f",
        expected_origin_key=None,
    ),
}

REF_FIELDS = ("approved", "approval_reference", "source_metadata")
ITEM_FIELDS = ("review_status", "provenance")


def _clean_nonempty_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApprovalError(f"Campo obrigatório ausente ou inválido na decisão humana: {field_name}.")
    return value.strip()


def assert_local_environment(*, allow_test_db: bool = False) -> str:
    """Block execution on synthetic previews, remote platforms, or wrong databases."""
    if getattr(settings, "SYNTHETIC_PREVIEW", False):
        raise ApprovalError("Operação bloqueada: SYNTHETIC_PREVIEW está ativo.")
    for marker in REMOTE_ENV_MARKERS:
        if os.environ.get(marker):
            raise ApprovalError(f"Operação bloqueada em ambiente remoto ({marker} presente).")
    if allow_test_db:
        return str(connection.settings_dict.get("NAME", ""))
    if connection.vendor != "postgresql":
        raise ApprovalError("Operação permitida exclusivamente no PostgreSQL local operacional.")
    host = connection.settings_dict.get("HOST", "")
    db_name = connection.settings_dict.get("NAME", "")
    if host not in LOCAL_HOSTS:
        raise ApprovalError("Operação bloqueada: host de banco fora de loopback local.")
    if db_name != EXPECTED_DATABASE:
        raise ApprovalError(
            f"Banco-alvo incorreto ({db_name!r}); esperado exclusivamente {EXPECTED_DATABASE!r}."
        )
    return db_name


def validate_identifiers(
    identifiers: list[str] | tuple[str, ...],
    *,
    registry: dict[str, CandidateSpec] = ALLOWED_CANDIDATES,
) -> list[str]:
    if not identifiers:
        raise ApprovalError("Informe explicitamente pelo menos um identificador permitido.")
    seen: list[str] = []
    for ident in identifiers:
        if not isinstance(ident, str) or ident not in registry:
            raise ApprovalError(
                f"Identificador não permitido para este procedimento: {ident!r}. "
                f"Permitidos: {', '.join(sorted(registry))}."
            )
        if ident in seen:
            raise ApprovalError(f"Identificador duplicado na solicitação: {ident}.")
        seen.append(ident)
    return seen


def load_human_decisions(
    decision_path: Path | None,
    identifiers: list[str],
    *,
    registry: dict[str, CandidateSpec] = ALLOWED_CANDIDATES,
) -> dict[str, dict[str, str]]:
    """Require an explicit, per-identifier human decision file scoped to local display only."""
    if decision_path is None:
        raise ApprovalError("Decisão humana explícita é obrigatória (--decision-file).")
    try:
        payload = json.loads(Path(decision_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ApprovalError("Não foi possível ler o arquivo JSON de decisão humana.") from exc
    if not isinstance(payload, dict):
        raise ApprovalError("Arquivo de decisão humana deve ser um objeto JSON.")
    if payload.get("schema_version") != 1:
        raise ApprovalError("schema_version da decisão humana deve ser 1.")
    if payload.get("environment") != EXPECTED_ENVIRONMENT:
        raise ApprovalError(
            f"Ambiente da decisão humana ({payload.get('environment')!r}) diverge de {EXPECTED_ENVIRONMENT!r}."
        )
    if payload.get("purpose") != "display":
        raise ApprovalError("Somente a finalidade 'display' é permitida por este procedimento.")
    raw_decisions = payload.get("decisions")
    if not isinstance(raw_decisions, dict):
        raise ApprovalError("Campo 'decisions' ausente ou inválido no arquivo de decisão humana.")

    validated: dict[str, dict[str, str]] = {}
    seen_receipts: set[str] = set()
    for ident in identifiers:
        entry = raw_decisions.get(ident)
        if not isinstance(entry, dict):
            raise ApprovalError(f"Nenhuma decisão humana registrada para {ident}.")
        if entry.get("decision") != "allow":
            raise ApprovalError(f"Decisão humana para {ident} não autoriza liberação (esperado 'allow').")
        if entry.get("permission") != "display":
            raise ApprovalError(f"Permissão para {ident} deve ser exclusivamente 'display'.")
        if entry.get("scope") != EXPECTED_ENVIRONMENT:
            raise ApprovalError(f"Escopo da decisão para {ident} deve ser {EXPECTED_ENVIRONMENT!r}.")
        reviewer = _clean_nonempty_str(entry.get("reviewer"), f"{ident}.reviewer")
        role = _clean_nonempty_str(entry.get("role"), f"{ident}.role")
        receipt = _clean_nonempty_str(entry.get("approval_reference"), f"{ident}.approval_reference")
        if receipt.upper().startswith("DATUMLEX-4D:"):
            raise ApprovalError(
                f"Referência de aprovação para {ident} não pode reutilizar recibo da Fase 4D."
            )
        if receipt in seen_receipts:
            raise ApprovalError(f"Referência de aprovação duplicada entre fontes: {receipt}.")
        seen_receipts.add(receipt)
        decided_at = _clean_nonempty_str(entry.get("decided_at"), f"{ident}.decided_at")
        try:
            datetime.fromisoformat(decided_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ApprovalError(f"Data decided_at inválida para {ident}.") from exc
        deliverable = _clean_nonempty_str(entry.get("deliverable"), f"{ident}.deliverable")
        expected_fp = _clean_nonempty_str(entry.get("expected_fingerprint"), f"{ident}.expected_fingerprint")
        spec = registry[ident]
        if expected_fp != spec.expected_fingerprint:
            raise ApprovalError(f"Fingerprint na decisão humana diverge do esperado para {ident}.")
        validated[ident] = {
            "receipt": receipt,
            "reviewer": reviewer,
            "role": role,
            "decided_at": decided_at,
            "scope": EXPECTED_ENVIRONMENT,
            "permission": "display",
            "decision": "allowed",
            "deliverable": deliverable,
            "expected_fingerprint": expected_fp,
        }
    return validated


def _persist_private_json(path: Path, data: dict[str, Any]) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(data, ensure_ascii=False, indent=2, default=str, sort_keys=True) + "\n").encode("utf-8")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ApprovalError(f"Arquivo de auditoria já existe e não será sobrescrito: {path}") from exc
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return hashlib.sha256(raw).hexdigest()


def _locate_candidate(
    spec: CandidateSpec, *, for_update: bool = False
) -> tuple[LegalReference | None, LegalCorpusItem]:
    item_qs = LegalCorpusItem.objects.select_for_update() if for_update else LegalCorpusItem.objects.all()
    if spec.has_reference:
        ref_qs = LegalReference.objects.select_for_update() if for_update else LegalReference.objects.all()
        try:
            ref = ref_qs.get(source_name=spec.source_name, identifier=spec.identifier)
        except LegalReference.DoesNotExist as exc:
            raise ApprovalError(f"LegalReference não encontrada para {spec.identifier}.") from exc
        try:
            item = item_qs.get(origin_key=f"reference:{ref.pk}")
        except LegalCorpusItem.DoesNotExist as exc:
            raise ApprovalError(f"LegalCorpusItem vinculado não encontrado para {spec.identifier}.") from exc
        if item.provenance.get("reference_id") != ref.pk:
            raise ApprovalError(f"Vínculo reference_id inconsistente em {spec.identifier}.")
        if ref.reference_type != spec.category or ref.source_institution != spec.source_institution:
            raise ApprovalError(f"Categoria ou instituição de LegalReference diverge em {spec.identifier}.")
        if ref.source_payload_hash != spec.expected_fingerprint:
            raise ApprovalError(f"Fingerprint de LegalReference diverge do esperado em {spec.identifier}.")
        if ref.thesis:
            raise ApprovalError(f"LegalReference de {spec.identifier} contém texto/tese inesperado.")
        if ref.title != item.title or ref.source_url != item.source_url:
            raise ApprovalError(f"Título ou URL diverge entre LegalReference e LegalCorpusItem em {spec.identifier}.")
    else:
        ref = None
        candidates = item_qs.filter(category=spec.category, court=spec.court)
        if spec.expected_origin_key:
            candidates = candidates.filter(origin_key=spec.expected_origin_key)
        else:
            candidates = candidates.filter(provenance__metadata__id=spec.identifier)
        rows = list(candidates[:2])
        if len(rows) != 1:
            raise ApprovalError(f"LegalCorpusItem único não encontrado para {spec.identifier}.")
        item = rows[0]
        if "reference_id" in (item.provenance or {}):
            raise ApprovalError(f"Item de jurisprudência {spec.identifier} possui reference_id inesperado.")

    metadata = (item.provenance or {}).get("metadata")
    if not isinstance(metadata, dict) or metadata.get("id") != spec.identifier:
        raise ApprovalError(f"Metadado interno id não corresponde a {spec.identifier}.")
    if item.category != spec.category or item.court != spec.court or item.source_name != spec.source_name:
        raise ApprovalError(f"Escopo/categoria/tribunal de {spec.identifier} diverge do esperado.")
    if item.fingerprint != spec.expected_fingerprint:
        raise ApprovalError(f"Fingerprint de LegalCorpusItem diverge do esperado em {spec.identifier}.")
    if item.excerpt:
        raise ApprovalError(f"Item {spec.identifier} contém trecho textual não vazio; aprovação bloqueada.")
    return ref, item


def _capture_state(ref: LegalReference | None, item: LegalCorpusItem) -> dict[str, Any]:
    return {
        "has_reference": ref is not None,
        "reference_pk": ref.pk if ref is not None else None,
        "item_pk": item.pk,
        "reference": {k: copy.deepcopy(getattr(ref, k)) for k in REF_FIELDS} if ref is not None else None,
        "item": {k: copy.deepcopy(getattr(item, k)) for k in ITEM_FIELDS},
    }


def _write_state(ref: LegalReference | None, item: LegalCorpusItem, saved: dict[str, Any]) -> None:
    if (ref.pk if ref is not None else None) != saved["reference_pk"] or item.pk != saved["item_pk"]:
        raise ApprovalError("Identidade dos registros divergiu durante escrita/restauração.")
    if ref is not None:
        LegalReference.objects.filter(pk=ref.pk).update(**saved["reference"])
    LegalCorpusItem.objects.filter(pk=item.pk).update(**saved["item"])


def _build_display_state(before: dict[str, Any], decision: dict[str, str]) -> dict[str, Any]:
    after = copy.deepcopy(before)
    after["item"]["review_status"] = "approved"
    after["item"]["provenance"] = {
        **after["item"]["provenance"],
        "permissions": {"display": "allowed"},
        "display_approval": decision,
    }
    if after["has_reference"]:
        after["reference"]["approved"] = True
        after["reference"]["approval_reference"] = decision["receipt"]
        after["reference"]["source_metadata"] = {
            **after["reference"]["source_metadata"],
            "permissions": {"display": "allowed"},
            "display_approval": decision,
        }
    return after


def _assert_security_invariants(
    expected_visible_item_pks: set[int],
    expected_visible_ref_pks: set[int],
    expected_fact_count: int,
) -> dict[str, int]:
    actual_items = set(published_items("display").values_list("pk", flat=True))
    actual_refs = set(published_references().values_list("pk", flat=True))
    if actual_items != expected_visible_item_pks:
        raise ApprovalError("Invariante de visibilidade de LegalCorpusItem violada.")
    if actual_refs != expected_visible_ref_pks:
        raise ApprovalError("Invariante de visibilidade de LegalReference violada.")
    if published_items("nlp").exists() or allowed_versions(use="nlp"):
        raise ApprovalError("Invariante violada: permissão NLP detectada.")
    if published_items("gemini").exists() or allowed_versions(use="gemini"):
        raise ApprovalError("Invariante violada: permissão Gemini detectada.")
    if (
        LegalCorpusItem.objects.filter(provenance__permissions__text="allowed").exists()
        or LegalReference.objects.filter(source_metadata__permissions__text="allowed").exists()
        or LegalReference.objects.filter(source_metadata__permissions__nlp="allowed").exists()
        or LegalReference.objects.filter(source_metadata__permissions__gemini="allowed").exists()
    ):
        raise ApprovalError("Invariante violada: permissão text/nlp/gemini detectada.")
    if FactProcess.objects.count() != expected_fact_count:
        raise ApprovalError("Invariante violada: contagem de fatos DataJud foi alterada.")
    return {
        "published_items": len(actual_items),
        "published_references": len(actual_refs),
        "pending_items": LegalCorpusItem.objects.filter(review_status="pending").count(),
        "text_grants": 0,
        "nlp_grants": 0,
        "gemini_grants": 0,
    }


def _configure_pg_transaction(*, read_only: bool, expected_db: str = EXPECTED_DATABASE) -> None:
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        if read_only:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SELECT current_database(), current_setting('transaction_read_only')")
            db_name, ro = cursor.fetchone()
            if db_name != expected_db or ro != "on":
                raise ApprovalError("PostgreSQL não confirmou banco operacional ou modo somente leitura.")
        else:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("SELECT current_database(), pg_try_advisory_xact_lock(%s)", (ADVISORY_LOCK_KEY,))
            db_name, locked = cursor.fetchone()
            if db_name != expected_db or not locked:
                raise ApprovalError("Banco operacional não confirmado ou bloqueio exclusivo indisponível.")


def check_candidates(
    identifiers: list[str] | tuple[str, ...] | None = None,
    *,
    registry: dict[str, CandidateSpec] = ALLOWED_CANDIDATES,
    allow_test_db: bool = False,
) -> dict[str, Any]:
    """Strictly read-only inspection of allowed candidates and global publication gates."""
    db_name = assert_local_environment(allow_test_db=allow_test_db)
    targets = validate_identifiers(list(identifiers) if identifiers else sorted(registry), registry=registry)
    with transaction.atomic(durable=True):
        _configure_pg_transaction(read_only=True, expected_db=db_name)
        items_summary: dict[str, Any] = {}
        for ident in targets:
            spec = registry[ident]
            ref, item = _locate_candidate(spec, for_update=False)
            perms = (item.provenance or {}).get("permissions") or {}
            items_summary[ident] = {
                "category": item.category,
                "court": item.court,
                "review_status": item.review_status,
                "permissions": perms,
                "fingerprint_verified": True,
                "has_reference": ref is not None,
                "reference_approved": ref.approved if ref is not None else None,
                "reference_permissions": ((ref.source_metadata or {}).get("permissions") or {}) if ref is not None else None,
                "excerpt_empty": item.excerpt == "",
                "eligible_for_display_approval": (
                    item.review_status == "pending"
                    and not perms
                    and (ref is None or (not ref.approved and not ((ref.source_metadata or {}).get("permissions") or {})))
                ),
            }
        counts = {
            "total_corpus_items": LegalCorpusItem.objects.count(),
            "pending_corpus_items": LegalCorpusItem.objects.filter(review_status="pending").count(),
            "published_display_items": published_items("display").count(),
            "published_references": published_references().count(),
            "nlp_grants": published_items("nlp").count(),
            "gemini_grants": published_items("gemini").count(),
            "text_grants": published_items("display").filter(provenance__permissions__text="allowed").count(),
        }
    return {"mode": "check", "database": db_name, "candidates": items_summary, "counts": counts}


def apply_display_approval(
    identifiers: list[str] | tuple[str, ...],
    *,
    decision_file: Path | None,
    snapshot_path: Path | None = None,
    receipt_path: Path | None = None,
    dry_run: bool = False,
    registry: dict[str, CandidateSpec] = ALLOWED_CANDIDATES,
    allow_test_db: bool = False,
) -> dict[str, Any]:
    """Approve display-only metadata visibility for explicitly decided candidates."""
    db_name = assert_local_environment(allow_test_db=allow_test_db)
    targets = validate_identifiers(list(identifiers), registry=registry)
    decisions = load_human_decisions(decision_file, targets, registry=registry)
    if not dry_run:
        if snapshot_path is None or receipt_path is None:
            raise ApprovalError("A aplicação real exige --snapshot e --receipt para auditoria e revogação.")
        snapshot_path = Path(snapshot_path)
        receipt_path = Path(receipt_path)
        if snapshot_path.resolve() == receipt_path.resolve():
            raise ApprovalError("--snapshot e --receipt devem apontar para arquivos distintos.")
        if snapshot_path.exists():
            raise ApprovalError(f"Arquivo de auditoria já existe e não será sobrescrito: {snapshot_path}")
        if receipt_path.exists():
            raise ApprovalError(f"Arquivo de auditoria já existe e não será sobrescrito: {receipt_path}")

    now_iso = timezone.localtime().isoformat(timespec="seconds")
    snapshot_sha256: str | None = None
    snapshot_written = False
    receipt_written = False
    report: dict[str, Any] = {}

    try:
        with transaction.atomic(durable=True):
            _configure_pg_transaction(read_only=False, expected_db=db_name)
            fact_count = FactProcess.objects.count()
            baseline_items = set(published_items("display").values_list("pk", flat=True))
            baseline_refs = set(published_references().values_list("pk", flat=True))
            _assert_security_invariants(baseline_items, baseline_refs, fact_count)

            locked: dict[str, tuple[LegalReference | None, LegalCorpusItem]] = {}
            before: dict[str, dict[str, Any]] = {}
            for ident in targets:
                ref, item = _locate_candidate(registry[ident], for_update=True)
                state = _capture_state(ref, item)
                if state["item"]["review_status"] != "pending" or (state["item"]["provenance"].get("permissions") or {}):
                    raise ApprovalError(
                        f"Fonte {ident} não está em estado pendente limpo (status={state['item']['review_status']!r})."
                    )
                if state["has_reference"] and (
                    state["reference"]["approved"]
                    or state["reference"]["approval_reference"]
                    or (state["reference"]["source_metadata"].get("permissions") or {})
                ):
                    raise ApprovalError(f"LegalReference de {ident} já possui aprovação ou permissões.")
                locked[ident] = (ref, item)
                before[ident] = state

            if not dry_run:
                snapshot_payload = {
                    "schema_version": 1,
                    "database": db_name,
                    "environment": EXPECTED_ENVIRONMENT,
                    "when": now_iso,
                    "targets": targets,
                    "before": before,
                    "decisions": decisions,
                    "fact_count": fact_count,
                }
                snapshot_sha256 = _persist_private_json(snapshot_path, snapshot_payload)
                snapshot_written = True

            expected_items = set(baseline_items)
            expected_refs = set(baseline_refs)
            for ident in targets:
                ref, item = locked[ident]
                after = _build_display_state(before[ident], decisions[ident])
                _write_state(ref, item, after)
                expected_items.add(item.pk)
                if ref is not None:
                    expected_refs.add(ref.pk)

            visibility = _assert_security_invariants(expected_items, expected_refs, fact_count)

            # Rehearse individual rollback inside a nested savepoint before committing.
            for ident in targets:
                ref, item = locked[ident]
                with transaction.atomic():
                    _write_state(ref, item, before[ident])
                    _assert_security_invariants(
                        expected_items - {item.pk},
                        expected_refs - ({ref.pk} if ref is not None else set()),
                        fact_count,
                    )
                    transaction.set_rollback(True)

            _assert_security_invariants(expected_items, expected_refs, fact_count)

            report = {
                "mode": "dry_run" if dry_run else "apply",
                "rolled_back": dry_run,
                "database": db_name,
                "when": now_iso,
                "targets": targets,
                "decisions": decisions,
                "snapshot_sha256": snapshot_sha256,
                "visibility": visibility,
                "reversible_per_source": True,
                "datajud_facts_preserved": fact_count,
            }

            if dry_run:
                transaction.set_rollback(True)
            else:
                _persist_private_json(receipt_path, report)
                receipt_written = True
    except Exception:
        if receipt_written and receipt_path is not None and Path(receipt_path).exists():
            Path(receipt_path).unlink(missing_ok=True)
        if snapshot_written and snapshot_path is not None and Path(snapshot_path).exists():
            Path(snapshot_path).unlink(missing_ok=True)
        raise

    return report


def revoke_display_approval(
    identifiers: list[str] | tuple[str, ...],
    *,
    snapshot_path: Path,
    receipt_path: Path,
    dry_run: bool = False,
    registry: dict[str, CandidateSpec] = ALLOWED_CANDIDATES,
    allow_test_db: bool = False,
) -> dict[str, Any]:
    """Individually revoke display approval using the verified pre-approval snapshot."""
    db_name = assert_local_environment(allow_test_db=allow_test_db)
    targets = validate_identifiers(list(identifiers), registry=registry)
    try:
        snapshot_bytes = Path(snapshot_path).read_bytes()
        snapshot = json.loads(snapshot_bytes.decode("utf-8"))
        receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ApprovalError("Snapshot ou recibo de aprovação inválido/ilegível.") from exc

    actual_sha = hashlib.sha256(snapshot_bytes).hexdigest()
    if actual_sha != receipt.get("snapshot_sha256"):
        raise ApprovalError("Hash SHA-256 do snapshot não confere com o recibo de aprovação.")
    if snapshot.get("database") != db_name:
        raise ApprovalError("Snapshot pertence a outro banco de dados.")

    now_iso = timezone.localtime().isoformat(timespec="seconds")
    with transaction.atomic(durable=True):
        _configure_pg_transaction(read_only=False, expected_db=db_name)
        fact_count = FactProcess.objects.count()
        baseline_items = set(published_items("display").values_list("pk", flat=True))
        baseline_refs = set(published_references().values_list("pk", flat=True))
        _assert_security_invariants(baseline_items, baseline_refs, fact_count)

        expected_items = set(baseline_items)
        expected_refs = set(baseline_refs)
        for ident in targets:
            if ident not in snapshot.get("before", {}) or ident not in snapshot.get("decisions", {}):
                raise ApprovalError(f"Snapshot não contém estado prévio para {ident}.")
            ref, item = _locate_candidate(registry[ident], for_update=True)
            observed = _capture_state(ref, item)
            expected_active = _build_display_state(snapshot["before"][ident], snapshot["decisions"][ident])
            if observed != expected_active:
                raise ApprovalError(
                    f"Estado atual de {ident} diverge do estado aprovado pelo recibo; revogação abortada."
                )
            _write_state(ref, item, snapshot["before"][ident])
            expected_items.discard(item.pk)
            if ref is not None:
                expected_refs.discard(ref.pk)

        visibility = _assert_security_invariants(expected_items, expected_refs, fact_count)
        if dry_run:
            transaction.set_rollback(True)

    return {
        "mode": "revoke_dry_run" if dry_run else "revoke",
        "rolled_back": dry_run,
        "database": db_name,
        "when": now_iso,
        "targets": targets,
        "snapshot_sha256": actual_sha,
        "visibility": visibility,
    }
