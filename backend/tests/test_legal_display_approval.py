"""Isolated synthetic tests for auditable local display-only legal source approval."""

from __future__ import annotations

from datetime import date
from importlib import import_module
import io
import json
import os
from pathlib import Path
import stat
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import TransactionTestCase, override_settings

from src.accounts.models import Court
from src.db.models import (
    DimClass,
    DimDegree,
    DimOrg,
    DimProcess,
    DimResult,
    DimTime,
    ExtractionRun,
    FactProcess,
    LegalCorpusItem,
    LegalCorpusTopicMatch,
    LegalReference,
)
from src.services.corpus_publication import allowed_versions, published_items, published_references, with_public_excerpt
from src.services.legal_display_approval import (
    ALLOWED_CANDIDATES,
    ApprovalError,
    EXPECTED_DATABASE,
    EXPECTED_ENVIRONMENT,
    apply_display_approval,
    assert_local_environment,
    check_candidates,
    revoke_display_approval,
)

JURIS_ID = "TJDFT:ACORDAO:1955493"
DOCTRINE_ID = "SENADO:RIL:61:241:237"
JURIS_FP = ALLOWED_CANDIDATES[JURIS_ID].expected_fingerprint
DOCTRINE_FP = ALLOWED_CANDIDATES[DOCTRINE_ID].expected_fingerprint


class LegalDisplayApprovalTests(TransactionTestCase):
    def _fixture_teardown(self):
        if connection.vendor != "postgresql":
            return super()._fixture_teardown()
        if not connection.settings_dict["NAME"].startswith("test_"):
            raise RuntimeError("Refusing cleanup outside a test database")
        tables = import_module("src.db.migrations.0011_nlp_history_guards").TABLES
        with connection.cursor() as cursor:
            for table in tables:
                cursor.execute(f"ALTER TABLE {table} DISABLE TRIGGER nlp_no_truncate")
        try:
            super()._fixture_teardown()
        finally:
            with connection.cursor() as cursor:
                for table in tables:
                    cursor.execute(f"ALTER TABLE {table} ENABLE TRIGGER nlp_no_truncate")

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.addCleanup(self.tmpdir.cleanup)

        self.user = get_user_model().objects.create_user(
            username="display-approval-tester",
            approved=True,
            must_change_password=False,
        )
        tjdft = Court.objects.get_or_create(code="TJDFT", defaults={"name": "TJDFT"})[0]
        self.user.courts.add(tjdft)
        self.client.force_login(self.user)

        dim_time = DimTime.objects.create(date=date(2025, 1, 15), year=2025, month=1, day=15, quarter=1)
        dim_class = DimClass.objects.create(code=198, name="Apelação Cível")
        dim_org = DimOrg.objects.create(court="TJDFT", code=1, name="Turma Cível")
        dim_degree = DimDegree.objects.create(code="G2", name="2º Grau")
        dim_proc = DimProcess.objects.create(number_process="00000010020258070001", secrecy_level=0)
        dim_res = DimResult.objects.create(name="desprovido")
        run = ExtractionRun.objects.create(status="completed", scope={"court": "TJDFT"})
        self.fact = FactProcess.objects.create(
            source_id="TJDFT:synth-001",
            process_dimension=dim_proc,
            court="TJDFT",
            degree_dimension=dim_degree,
            result=dim_res,
            time=dim_time,
            process_class=dim_class,
            organization=dim_org,
            last_run=run,
            raw_payload={"synthetic": True},
            payload_hash="1" * 64,
        )

        # Two pre-approved STJ precedents (simulating Phase 4D baseline, untouched by this workflow).
        self.stj_sumula_ref, self.stj_sumula_item = self._create_reference_pair(
            identifier="STJ:SUMULA:37",
            reference_type="precedent",
            source_institution="STJ",
            source_name="STJ",
            title="Súmula 37 do STJ (sintética)",
            fingerprint="a" * 64,
            approved=True,
            approval_reference="DATUMLEX-4D:STJ:SUMULA:37",
            permissions={"display": "allowed"},
            court="STJ",
        )
        self.stj_tema_ref, self.stj_tema_item = self._create_reference_pair(
            identifier="STJ:TEMA:1111",
            reference_type="precedent",
            source_institution="STJ",
            source_name="STJ",
            title="Tema Repetitivo 1111 do STJ (sintético)",
            fingerprint="b" * 64,
            approved=True,
            approval_reference="DATUMLEX-4D:STJ:TEMA:1111",
            permissions={"display": "allowed"},
            court="STJ",
        )

        # Six pending sources (2 allowlisted + 4 disallowed/deferred).
        self.juris_item = self._create_jurisprudence_item(
            identifier=JURIS_ID,
            court="TJDFT",
            source_name="TJDFT",
            origin_key=ALLOWED_CANDIDATES[JURIS_ID].expected_origin_key,
            fingerprint=JURIS_FP,
            title="Acórdão sintético 1955493 — responsabilidade civil",
            url="https://pesquisajuris.tjdft.jus.br/IndexadorAcordaos-web/sistj",
        )
        self.doctrine_ref, self.doctrine_item = self._create_reference_pair(
            identifier=DOCTRINE_ID,
            reference_type="doctrine",
            source_institution="Senado",
            source_name="Senado Federal",
            title="Artigo sintético RIL 241 — responsabilidade civil",
            fingerprint=DOCTRINE_FP,
            approved=False,
            approval_reference="",
            permissions={},
            court="",
            url="https://www12.senado.leg.br/ril/edicoes/61/241/ril_v61_n241_p237",
        )
        self.med_tjdft = self._create_jurisprudence_item(
            identifier="TJDFT:ACORDAO:1218333",
            court="TJDFT",
            source_name="TJDFT",
            origin_key="nlp:TJDFT:synth-med-1218333",
            fingerprint="c" * 64,
            title="Acórdão sintético erro médico TJDFT",
            url="https://pesquisajuris.tjdft.jus.br/IndexadorAcordaos-web/sistj",
        )
        self.med_stj = self._create_jurisprudence_item(
            identifier="STJ:RESP:1145728:MG",
            court="STJ",
            source_name="STJ",
            origin_key="nlp:STJ:synth-med-1145728",
            fingerprint="d" * 64,
            title="Acórdão sintético erro médico STJ",
            url="https://scon.stj.jus.br/SCON/",
        )
        self.tjpr_pending = self._create_jurisprudence_item(
            identifier="TJPR:ACORDAO:4100000023658871",
            court="TJPR",
            source_name="TJPR",
            origin_key="nlp:TJPR:synth-4100000023658871",
            fingerprint="e" * 64,
            title="Acórdão sintético TJPR",
            url="https://portal.tjpr.jus.br/jurisprudencia/",
        )
        self.ril_2020_ref, self.ril_2020_item = self._create_reference_pair(
            identifier="SENADO:RIL:57:226:71",
            reference_type="doctrine",
            source_institution="Senado",
            source_name="Senado Federal",
            title="Artigo sintético RIL 226",
            fingerprint="f" * 64,
            approved=False,
            approval_reference="",
            permissions={},
            court="",
            url="https://www12.senado.leg.br/ril/edicoes/57/226/ril_v57_n226_p71",
        )

    def _create_jurisprudence_item(
        self,
        *,
        identifier: str,
        court: str,
        source_name: str,
        origin_key: str,
        fingerprint: str,
        title: str,
        url: str,
    ) -> LegalCorpusItem:
        item = LegalCorpusItem.objects.create(
            origin_key=origin_key,
            category="jurisprudence",
            court=court,
            title=title,
            excerpt="",
            source_name=source_name,
            source_url=url,
            content_kind="metadata_only",
            date=date(2024, 12, 11),
            fingerprint=fingerprint,
            review_status="pending",
            provenance={
                "source_manifest": "synthetic-manifest",
                "metadata": {"id": identifier, "category": "jurisprudence", "court": court},
            },
        )
        LegalCorpusTopicMatch.objects.create(item=item, topic="dano-moral", matched_terms=["dano moral"])
        return item

    def _create_reference_pair(
        self,
        *,
        identifier: str,
        reference_type: str,
        source_institution: str,
        source_name: str,
        title: str,
        fingerprint: str,
        approved: bool,
        approval_reference: str,
        permissions: dict[str, str],
        court: str,
        url: str = "https://www.stj.jus.br/",
    ) -> tuple[LegalReference, LegalCorpusItem]:
        source_metadata = {
            "source_manifest": "synthetic-manifest",
            "metadata": {"id": identifier, "category": reference_type},
        }
        if permissions:
            source_metadata["permissions"] = dict(permissions)
        ref = LegalReference.objects.create(
            reference_type=reference_type,
            source_institution=source_institution,
            identifier=identifier,
            title=title,
            thesis="",
            source_name=source_name,
            source_url=url,
            source_payload_hash=fingerprint,
            approval_reference=approval_reference,
            approved=approved,
            source_metadata=source_metadata,
        )
        provenance = {
            "reference_id": ref.pk,
            "source_manifest": "synthetic-manifest",
            "metadata": {"id": identifier, "category": reference_type},
        }
        if permissions:
            provenance["permissions"] = dict(permissions)
        item = LegalCorpusItem.objects.create(
            origin_key=f"reference:{ref.pk}",
            category=reference_type,
            court=court,
            title=title,
            excerpt="",
            source_name=source_name,
            source_url=url,
            content_kind="metadata_only",
            date=date(2024, 3, 1),
            fingerprint=fingerprint,
            review_status="approved" if approved else "pending",
            provenance=provenance,
        )
        LegalCorpusTopicMatch.objects.create(item=item, topic="dano-moral", matched_terms=["dano moral"])
        return ref, item

    def _write_decision_file(
        self,
        entries: dict[str, dict],
        *,
        filename: str = "decisao.json",
        purpose: str = "display",
        environment: str = EXPECTED_ENVIRONMENT,
        schema_version: int = 1,
    ) -> Path:
        path = self.tmp_path / filename
        payload = {
            "schema_version": schema_version,
            "environment": environment,
            "purpose": purpose,
            "decisions": entries,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _valid_entry(self, ident: str, **overrides) -> dict:
        fp = ALLOWED_CANDIDATES[ident].expected_fingerprint
        base = {
            "decision": "allow",
            "permission": "display",
            "reviewer": "Responsável Sintético",
            "role": "revisor humano",
            "approval_reference": f"DATUMLEX-4G:{ident}",
            "decided_at": "2026-11-22T20:00:00-03:00",
            "scope": EXPECTED_ENVIRONMENT,
            "deliverable": "metadados e link oficial sem texto integral",
            "expected_fingerprint": fp,
        }
        base.update(overrides)
        return base

    # 1. Tentativa sem autorização humana ou decisão inválida
    def test_requires_explicit_valid_human_decision(self):
        with self.assertRaisesRegex(ApprovalError, "Decisão humana explícita"):
            apply_display_approval([JURIS_ID], decision_file=None, dry_run=True, allow_test_db=True)

        missing_entry = self._write_decision_file({DOCTRINE_ID: self._valid_entry(DOCTRINE_ID)}, filename="missing.json")
        with self.assertRaisesRegex(ApprovalError, "Nenhuma decisão humana"):
            apply_display_approval([JURIS_ID], decision_file=missing_entry, dry_run=True, allow_test_db=True)

        denied = self._write_decision_file({JURIS_ID: self._valid_entry(JURIS_ID, decision="deny")}, filename="deny.json")
        with self.assertRaisesRegex(ApprovalError, "não autoriza liberação"):
            apply_display_approval([JURIS_ID], decision_file=denied, dry_run=True, allow_test_db=True)

        for forbidden_purpose in ("text", "nlp", "gemini"):
            bad_purpose = self._write_decision_file(
                {JURIS_ID: self._valid_entry(JURIS_ID)},
                filename=f"bad_purpose_{forbidden_purpose}.json",
                purpose=forbidden_purpose,
            )
            with self.assertRaisesRegex(ApprovalError, "Somente a finalidade 'display'"):
                apply_display_approval([JURIS_ID], decision_file=bad_purpose, dry_run=True, allow_test_db=True)

            bad_perm = self._write_decision_file(
                {JURIS_ID: self._valid_entry(JURIS_ID, permission=forbidden_purpose)},
                filename=f"bad_perm_{forbidden_purpose}.json",
            )
            with self.assertRaisesRegex(ApprovalError, "exclusivamente 'display'"):
                apply_display_approval([JURIS_ID], decision_file=bad_perm, dry_run=True, allow_test_db=True)

        reused_4d = self._write_decision_file(
            {JURIS_ID: self._valid_entry(JURIS_ID, approval_reference="DATUMLEX-4D:STJ:SUMULA:37")},
            filename="reused4d.json",
        )
        with self.assertRaisesRegex(ApprovalError, "Fase 4D"):
            apply_display_approval([JURIS_ID], decision_file=reused_4d, dry_run=True, allow_test_db=True)

        dup_ref = self._write_decision_file(
            {
                JURIS_ID: self._valid_entry(JURIS_ID, approval_reference="DATUMLEX-4G:SAME"),
                DOCTRINE_ID: self._valid_entry(DOCTRINE_ID, approval_reference="DATUMLEX-4G:SAME"),
            },
            filename="dupref.json",
        )
        with self.assertRaisesRegex(ApprovalError, "duplicada"):
            apply_display_approval([JURIS_ID, DOCTRINE_ID], decision_file=dup_ref, dry_run=True, allow_test_db=True)

        wrong_env = self._write_decision_file(
            {JURIS_ID: self._valid_entry(JURIS_ID)},
            filename="wrongenv.json",
            environment="remote:railway",
        )
        with self.assertRaisesRegex(ApprovalError, "Ambiente da decisão humana"):
            apply_display_approval([JURIS_ID], decision_file=wrong_env, dry_run=True, allow_test_db=True)

        bad_date = self._write_decision_file(
            {JURIS_ID: self._valid_entry(JURIS_ID, decided_at="not-a-date")},
            filename="baddate.json",
        )
        with self.assertRaisesRegex(ApprovalError, "decided_at"):
            apply_display_approval([JURIS_ID], decision_file=bad_date, dry_run=True, allow_test_db=True)

    # 2. Identificador fora da lista permitida
    def test_rejects_disallowed_or_duplicate_identifiers(self):
        decision = self._write_decision_file({JURIS_ID: self._valid_entry(JURIS_ID)})
        disallowed = [
            "TJDFT:ACORDAO:1218333",
            "STJ:RESP:1145728:MG",
            "TJPR:ACORDAO:4100000023658871",
            "SENADO:RIL:57:226:71",
            "STJ:SUMULA:37",
            "STJ:TEMA:1111",
            "UNKNOWN:SOURCE:999",
        ]
        for ident in disallowed:
            with self.assertRaisesRegex(ApprovalError, "Identificador não permitido"):
                apply_display_approval([ident], decision_file=decision, dry_run=True, allow_test_db=True)
            with self.assertRaisesRegex(ApprovalError, "Identificador não permitido"):
                check_candidates([ident], allow_test_db=True)

        with self.assertRaisesRegex(ApprovalError, "pelo menos um identificador"):
            apply_display_approval([], decision_file=decision, dry_run=True, allow_test_db=True)
        with self.assertRaisesRegex(ApprovalError, "duplicado"):
            apply_display_approval([JURIS_ID, JURIS_ID], decision_file=decision, dry_run=True, allow_test_db=True)

    # 3. Banco errado / ambiente remoto / SYNTHETIC_PREVIEW
    def test_environment_and_database_guards(self):
        with override_settings(SYNTHETIC_PREVIEW=True):
            with self.assertRaisesRegex(ApprovalError, "SYNTHETIC_PREVIEW"):
                assert_local_environment(allow_test_db=True)

        with patch.dict(os.environ, {"RAILWAY_ENVIRONMENT_NAME": "production"}, clear=False):
            with self.assertRaisesRegex(ApprovalError, "ambiente remoto"):
                assert_local_environment(allow_test_db=True)

        with patch.dict(os.environ, {"VERCEL": "1"}, clear=False):
            with self.assertRaisesRegex(ApprovalError, "ambiente remoto"):
                assert_local_environment(allow_test_db=True)

        # Non-operational test DB (SQLite or test_* PostgreSQL) must be rejected when allow_test_db=False.
        expected_guard_msg = (
            "Banco-alvo incorreto" if connection.vendor == "postgresql" else "PostgreSQL local operacional"
        )
        with self.assertRaisesRegex(ApprovalError, expected_guard_msg):
            assert_local_environment(allow_test_db=False)
        with self.assertRaisesRegex(CommandError, expected_guard_msg):
            call_command("manage_legal_display_approval", "--check", stdout=io.StringIO())

        with patch("src.services.legal_display_approval.connection") as mock_conn:
            mock_conn.vendor = "postgresql"
            mock_conn.settings_dict = {"HOST": "postgres.railway.internal", "NAME": EXPECTED_DATABASE}
            with self.assertRaisesRegex(ApprovalError, "loopback local"):
                assert_local_environment(allow_test_db=False)

            mock_conn.settings_dict = {"HOST": "127.0.0.1", "NAME": "datumlex_other_db"}
            with self.assertRaisesRegex(ApprovalError, "Banco-alvo incorreto"):
                assert_local_environment(allow_test_db=False)

            mock_conn.settings_dict = {"HOST": "127.0.0.1", "NAME": EXPECTED_DATABASE}
            self.assertEqual(assert_local_environment(allow_test_db=False), EXPECTED_DATABASE)

    # 4. Fonte inexistente
    def test_missing_source_fails_closed(self):
        decision = self._write_decision_file(
            {
                JURIS_ID: self._valid_entry(JURIS_ID),
                DOCTRINE_ID: self._valid_entry(DOCTRINE_ID),
            }
        )
        self.juris_item.delete()
        with self.assertRaisesRegex(ApprovalError, "LegalCorpusItem único não encontrado"):
            apply_display_approval([JURIS_ID], decision_file=decision, dry_run=True, allow_test_db=True)

        self.doctrine_item.delete()
        with self.assertRaisesRegex(ApprovalError, "LegalCorpusItem vinculado não encontrado"):
            apply_display_approval([DOCTRINE_ID], decision_file=decision, dry_run=True, allow_test_db=True)

        self.doctrine_ref.delete()
        with self.assertRaisesRegex(ApprovalError, "LegalReference não encontrada"):
            apply_display_approval([DOCTRINE_ID], decision_file=decision, dry_run=True, allow_test_db=True)

    # 5. Fingerprint divergente ou texto/tese presente
    def test_divergent_fingerprint_and_nonempty_text_blocked(self):
        wrong_fp_decision = self._write_decision_file(
            {JURIS_ID: self._valid_entry(JURIS_ID, expected_fingerprint="0" * 64)},
            filename="wrong_fp.json",
        )
        with self.assertRaisesRegex(ApprovalError, "Fingerprint na decisão humana diverge"):
            apply_display_approval([JURIS_ID], decision_file=wrong_fp_decision, dry_run=True, allow_test_db=True)

        valid_decision = self._write_decision_file(
            {
                JURIS_ID: self._valid_entry(JURIS_ID),
                DOCTRINE_ID: self._valid_entry(DOCTRINE_ID),
            }
        )

        LegalCorpusItem.objects.filter(pk=self.juris_item.pk).update(fingerprint="9" * 64)
        with self.assertRaisesRegex(ApprovalError, "Fingerprint de LegalCorpusItem diverge"):
            apply_display_approval([JURIS_ID], decision_file=valid_decision, dry_run=True, allow_test_db=True)
        LegalCorpusItem.objects.filter(pk=self.juris_item.pk).update(fingerprint=JURIS_FP)

        LegalReference.objects.filter(pk=self.doctrine_ref.pk).update(source_payload_hash="8" * 64)
        with self.assertRaisesRegex(ApprovalError, "Fingerprint de LegalReference diverge"):
            apply_display_approval([DOCTRINE_ID], decision_file=valid_decision, dry_run=True, allow_test_db=True)
        LegalReference.objects.filter(pk=self.doctrine_ref.pk).update(source_payload_hash=DOCTRINE_FP)

        LegalCorpusItem.objects.filter(pk=self.juris_item.pk).update(excerpt="Texto integral indevido")
        with self.assertRaisesRegex(ApprovalError, "trecho textual não vazio"):
            apply_display_approval([JURIS_ID], decision_file=valid_decision, dry_run=True, allow_test_db=True)
        LegalCorpusItem.objects.filter(pk=self.juris_item.pk).update(excerpt="")

        LegalReference.objects.filter(pk=self.doctrine_ref.pk).update(thesis="Tese não autorizada")
        with self.assertRaisesRegex(ApprovalError, "texto/tese inesperado"):
            apply_display_approval([DOCTRINE_ID], decision_file=valid_decision, dry_run=True, allow_test_db=True)

    # 6. Estado já aprovado ou rejeitado
    def test_already_approved_or_rejected_state_blocked(self):
        decision = self._write_decision_file(
            {
                JURIS_ID: self._valid_entry(JURIS_ID),
                DOCTRINE_ID: self._valid_entry(DOCTRINE_ID),
            }
        )
        LegalCorpusItem.objects.filter(pk=self.juris_item.pk).update(review_status="approved")
        with self.assertRaisesRegex(ApprovalError, "estado pendente limpo"):
            apply_display_approval([JURIS_ID], decision_file=decision, dry_run=True, allow_test_db=True)

        LegalCorpusItem.objects.filter(pk=self.juris_item.pk).update(review_status="rejected")
        with self.assertRaisesRegex(ApprovalError, "estado pendente limpo"):
            apply_display_approval([JURIS_ID], decision_file=decision, dry_run=True, allow_test_db=True)

        LegalReference.objects.filter(pk=self.doctrine_ref.pk).update(approved=True)
        with self.assertRaisesRegex(ApprovalError, "já possui aprovação"):
            apply_display_approval([DOCTRINE_ID], decision_file=decision, dry_run=True, allow_test_db=True)

    # 7. Falha no meio da transação (atomicidade e limpeza de arquivos)
    def test_mid_transaction_failure_rolls_back_and_cleans_snapshot(self):
        decision = self._write_decision_file(
            {
                JURIS_ID: self._valid_entry(JURIS_ID),
                DOCTRINE_ID: self._valid_entry(DOCTRINE_ID),
            }
        )
        snapshot = self.tmp_path / "snap_fail.json"
        receipt = self.tmp_path / "rcpt_fail.json"

        from src.services import legal_display_approval as svc

        real_write = svc._write_state
        calls = {"count": 0}

        def boom_on_second(ref, item, saved):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("falha simulada no meio da transação")
            return real_write(ref, item, saved)

        with patch("src.services.legal_display_approval._write_state", side_effect=boom_on_second):
            with self.assertRaisesRegex(RuntimeError, "falha simulada"):
                apply_display_approval(
                    [JURIS_ID, DOCTRINE_ID],
                    decision_file=decision,
                    snapshot_path=snapshot,
                    receipt_path=receipt,
                    dry_run=False,
                    allow_test_db=True,
                )

        # DB fully rolled back and partial audit files removed.
        self.juris_item.refresh_from_db()
        self.doctrine_ref.refresh_from_db()
        self.doctrine_item.refresh_from_db()
        self.assertEqual(self.juris_item.review_status, "pending")
        self.assertFalse(self.doctrine_ref.approved)
        self.assertEqual(self.doctrine_item.review_status, "pending")
        self.assertFalse(snapshot.exists())
        self.assertFalse(receipt.exists())

        # Existing audit files are never overwritten.
        existing = self.tmp_path / "already.json"
        existing.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(ApprovalError, "já existe"):
            apply_display_approval(
                [JURIS_ID],
                decision_file=decision,
                snapshot_path=existing,
                receipt_path=receipt,
                dry_run=False,
                allow_test_db=True,
            )
        with self.assertRaisesRegex(ApprovalError, "já existe"):
            apply_display_approval(
                [JURIS_ID],
                decision_file=decision,
                snapshot_path=snapshot,
                receipt_path=existing,
                dry_run=False,
                allow_test_db=True,
            )
        with self.assertRaisesRegex(ApprovalError, "arquivos distintos"):
            apply_display_approval(
                [JURIS_ID],
                decision_file=decision,
                snapshot_path=snapshot,
                receipt_path=snapshot,
                dry_run=False,
                allow_test_db=True,
            )

    # 8. Aprovação isolada da jurisprudência + --check + --dry-run
    def test_isolated_jurisprudence_approval_and_check_dry_run(self):
        check_report = check_candidates(allow_test_db=True)
        self.assertEqual(check_report["mode"], "check")
        self.assertTrue(check_report["candidates"][JURIS_ID]["eligible_for_display_approval"])
        self.assertTrue(check_report["candidates"][DOCTRINE_ID]["eligible_for_display_approval"])
        self.assertEqual(check_report["counts"]["pending_corpus_items"], 6)
        self.assertEqual(check_report["counts"]["published_display_items"], 2)

        decision = self._write_decision_file({JURIS_ID: self._valid_entry(JURIS_ID)})
        dry = apply_display_approval([JURIS_ID], decision_file=decision, dry_run=True, allow_test_db=True)
        self.assertEqual(dry["mode"], "dry_run")
        self.assertTrue(dry["rolled_back"])
        self.assertEqual(dry["visibility"]["published_items"], 3)
        self.assertEqual(dry["visibility"]["pending_items"], 5)

        # DB must remain untouched after dry-run.
        self.juris_item.refresh_from_db()
        self.assertEqual(self.juris_item.review_status, "pending")
        self.assertEqual(published_items("display").count(), 2)

        # Real isolated apply for jurisprudence only.
        snapshot = self.tmp_path / "juris_snap.json"
        receipt = self.tmp_path / "juris_rcpt.json"
        applied = apply_display_approval(
            [JURIS_ID],
            decision_file=decision,
            snapshot_path=snapshot,
            receipt_path=receipt,
            dry_run=False,
            allow_test_db=True,
        )
        self.assertEqual(applied["mode"], "apply")
        self.assertFalse(applied["rolled_back"])
        self.assertEqual(applied["visibility"]["published_items"], 3)
        self.assertEqual(applied["visibility"]["published_references"], 2)
        self.assertEqual(applied["visibility"]["pending_items"], 5)
        self.assertEqual(stat.S_IMODE(snapshot.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)

        self.juris_item.refresh_from_db()
        self.doctrine_ref.refresh_from_db()
        self.doctrine_item.refresh_from_db()
        self.assertEqual(self.juris_item.review_status, "approved")
        self.assertEqual(self.juris_item.provenance["permissions"], {"display": "allowed"})
        self.assertEqual(self.juris_item.provenance["display_approval"]["receipt"], f"DATUMLEX-4G:{JURIS_ID}")
        # Doctrine and other 4 pending sources remain strictly pending.
        self.assertFalse(self.doctrine_ref.approved)
        self.assertEqual(self.doctrine_item.review_status, "pending")
        self.assertEqual(LegalCorpusItem.objects.filter(review_status="pending").count(), 5)

        # API exposes approved jurisprudence metadata with empty excerpt; doctrine stays 404.
        resp_juris = self.client.get(f"/api/corpus/{self.juris_item.pk}/")
        self.assertEqual(resp_juris.status_code, 200)
        self.assertEqual(resp_juris.json()["excerpt"], "")
        self.assertEqual(self.client.get(f"/api/corpus/{self.doctrine_item.pk}/").status_code, 404)

    # 9. Aprovação isolada da doutrina (LegalReference + LegalCorpusItem)
    def test_isolated_doctrine_approval_updates_both_models_atomically(self):
        decision = self._write_decision_file({DOCTRINE_ID: self._valid_entry(DOCTRINE_ID)})
        snapshot = self.tmp_path / "doc_snap.json"
        receipt = self.tmp_path / "doc_rcpt.json"

        applied = apply_display_approval(
            [DOCTRINE_ID],
            decision_file=decision,
            snapshot_path=snapshot,
            receipt_path=receipt,
            dry_run=False,
            allow_test_db=True,
        )
        self.assertEqual(applied["visibility"]["published_items"], 3)
        self.assertEqual(applied["visibility"]["published_references"], 3)
        self.assertEqual(applied["visibility"]["pending_items"], 5)

        self.doctrine_ref.refresh_from_db()
        self.doctrine_item.refresh_from_db()
        self.juris_item.refresh_from_db()

        self.assertTrue(self.doctrine_ref.approved)
        self.assertEqual(self.doctrine_ref.approval_reference, f"DATUMLEX-4G:{DOCTRINE_ID}")
        self.assertEqual(self.doctrine_ref.source_metadata["permissions"], {"display": "allowed"})
        self.assertEqual(self.doctrine_item.review_status, "approved")
        self.assertEqual(self.doctrine_item.provenance["permissions"], {"display": "allowed"})
        # Jurisprudence and other 4 pending sources remain untouched.
        self.assertEqual(self.juris_item.review_status, "pending")
        self.assertEqual(LegalCorpusItem.objects.filter(review_status="pending").count(), 5)

        resp_doc = self.client.get(f"/api/corpus/{self.doctrine_item.pk}/")
        self.assertEqual(resp_doc.status_code, 200)
        self.assertEqual(resp_doc.json()["excerpt"], "")
        self.assertEqual(self.client.get(f"/api/corpus/{self.juris_item.pk}/").status_code, 404)

    # 10 & 11. Preservação das demais pendentes + bloqueio total de text, nlp e gemini
    def test_both_approved_preserves_other_pending_and_blocks_text_nlp_gemini(self):
        decision = self._write_decision_file(
            {
                JURIS_ID: self._valid_entry(JURIS_ID),
                DOCTRINE_ID: self._valid_entry(DOCTRINE_ID),
            }
        )
        snapshot = self.tmp_path / "both_snap.json"
        receipt = self.tmp_path / "both_rcpt.json"

        applied = apply_display_approval(
            [JURIS_ID, DOCTRINE_ID],
            decision_file=decision,
            snapshot_path=snapshot,
            receipt_path=receipt,
            dry_run=False,
            allow_test_db=True,
        )
        self.assertEqual(applied["visibility"]["published_items"], 4)
        self.assertEqual(applied["visibility"]["published_references"], 3)
        self.assertEqual(applied["visibility"]["pending_items"], 4)
        self.assertEqual(applied["visibility"]["text_grants"], 0)
        self.assertEqual(applied["visibility"]["nlp_grants"], 0)
        self.assertEqual(applied["visibility"]["gemini_grants"], 0)

        # Remaining 4 pending items (medical error + TJPR + RIL 2020) stay strictly pending and invisible.
        for untouched in (self.med_tjdft, self.med_stj, self.tjpr_pending, self.ril_2020_item):
            untouched.refresh_from_db()
            self.assertEqual(untouched.review_status, "pending")
            self.assertEqual((untouched.provenance or {}).get("permissions"), None)
            self.assertEqual(self.client.get(f"/api/corpus/{untouched.pk}/").status_code, 404)
        self.ril_2020_ref.refresh_from_db()
        self.assertFalse(self.ril_2020_ref.approved)

        # STJ precedents and DataJud facts remain completely untouched.
        self.stj_sumula_ref.refresh_from_db()
        self.stj_tema_ref.refresh_from_db()
        self.assertEqual(self.stj_sumula_ref.approval_reference, "DATUMLEX-4D:STJ:SUMULA:37")
        self.assertEqual(self.stj_tema_ref.approval_reference, "DATUMLEX-4D:STJ:TEMA:1111")
        self.assertEqual(FactProcess.objects.count(), 1)

        # text, nlp, and gemini remain 100% blocked.
        self.assertEqual(published_items("nlp").count(), 0)
        self.assertEqual(published_items("gemini").count(), 0)
        self.assertEqual(allowed_versions(use="nlp"), {})
        self.assertEqual(allowed_versions(use="gemini"), {})
        self.assertFalse(LegalCorpusItem.objects.filter(provenance__permissions__text="allowed").exists())
        self.assertFalse(LegalReference.objects.filter(source_metadata__permissions__text="allowed").exists())
        annotated = {
            row.pk: row.public_excerpt
            for row in with_public_excerpt(published_items("display"))
        }
        self.assertEqual(annotated[self.juris_item.pk], "")
        self.assertEqual(annotated[self.doctrine_item.pk], "")

    # 12. Revogação individual, simulação, integridade do snapshot e detecção de desvio
    def test_individual_revocation_restores_exact_state_and_verifies_snapshot(self):
        before_juris = (self.juris_item.review_status, dict(self.juris_item.provenance))
        before_doc_ref = (
            self.doctrine_ref.approved,
            self.doctrine_ref.approval_reference,
            dict(self.doctrine_ref.source_metadata),
        )
        before_doc_item = (self.doctrine_item.review_status, dict(self.doctrine_item.provenance))

        decision = self._write_decision_file(
            {
                JURIS_ID: self._valid_entry(JURIS_ID),
                DOCTRINE_ID: self._valid_entry(DOCTRINE_ID),
            }
        )
        snapshot = self.tmp_path / "rev_snap.json"
        receipt = self.tmp_path / "rev_rcpt.json"
        apply_display_approval(
            [JURIS_ID, DOCTRINE_ID],
            decision_file=decision,
            snapshot_path=snapshot,
            receipt_path=receipt,
            dry_run=False,
            allow_test_db=True,
        )

        # Dry-run revocation leaves state unchanged.
        sim = revoke_display_approval(
            [JURIS_ID], snapshot_path=snapshot, receipt_path=receipt, dry_run=True, allow_test_db=True
        )
        self.assertEqual(sim["mode"], "revoke_dry_run")
        self.assertTrue(sim["rolled_back"])
        self.assertEqual(sim["visibility"]["published_items"], 3)
        self.juris_item.refresh_from_db()
        self.assertEqual(self.juris_item.review_status, "approved")

        # Tampered snapshot rejected by SHA-256 verification.
        tampered = self.tmp_path / "tampered_snap.json"
        tampered.write_text(snapshot.read_text(encoding="utf-8") + " ", encoding="utf-8")
        with self.assertRaisesRegex(ApprovalError, "SHA-256"):
            revoke_display_approval(
                [JURIS_ID], snapshot_path=tampered, receipt_path=receipt, dry_run=False, allow_test_db=True
            )

        # Revoke only jurisprudence first; doctrine stays approved.
        rev_juris = revoke_display_approval(
            [JURIS_ID], snapshot_path=snapshot, receipt_path=receipt, dry_run=False, allow_test_db=True
        )
        self.assertEqual(rev_juris["mode"], "revoke")
        self.assertFalse(rev_juris["rolled_back"])
        self.assertEqual(rev_juris["visibility"]["published_items"], 3)
        self.assertEqual(rev_juris["visibility"]["published_references"], 3)
        self.juris_item.refresh_from_db()
        self.doctrine_ref.refresh_from_db()
        self.assertEqual((self.juris_item.review_status, self.juris_item.provenance), before_juris)
        self.assertTrue(self.doctrine_ref.approved)

        # State drift blocks revocation without overwriting unexpected edits.
        drifted_meta = dict(self.doctrine_ref.source_metadata)
        drifted_meta["manual_note"] = "edited-outside-procedure"
        LegalReference.objects.filter(pk=self.doctrine_ref.pk).update(source_metadata=drifted_meta)
        with self.assertRaisesRegex(ApprovalError, "Estado atual .* diverge"):
            revoke_display_approval(
                [DOCTRINE_ID], snapshot_path=snapshot, receipt_path=receipt, dry_run=False, allow_test_db=True
            )
        # Restore active state and perform clean doctrine revocation.
        drifted_meta.pop("manual_note")
        LegalReference.objects.filter(pk=self.doctrine_ref.pk).update(source_metadata=drifted_meta)

        rev_doc = revoke_display_approval(
            [DOCTRINE_ID], snapshot_path=snapshot, receipt_path=receipt, dry_run=False, allow_test_db=True
        )
        self.assertEqual(rev_doc["visibility"]["published_items"], 2)
        self.assertEqual(rev_doc["visibility"]["published_references"], 2)
        self.assertEqual(rev_doc["visibility"]["pending_items"], 6)

        self.doctrine_ref.refresh_from_db()
        self.doctrine_item.refresh_from_db()
        self.assertEqual(
            (self.doctrine_ref.approved, self.doctrine_ref.approval_reference, self.doctrine_ref.source_metadata),
            before_doc_ref,
        )
        self.assertEqual((self.doctrine_item.review_status, self.doctrine_item.provenance), before_doc_item)
        self.assertEqual(published_references().count(), 2)

    def test_management_command_lifecycle_with_mocked_local_env(self):
        decision = self._write_decision_file({JURIS_ID: self._valid_entry(JURIS_ID)}, filename="cli_dec.json")
        snapshot = self.tmp_path / "cli_snap.json"
        receipt = self.tmp_path / "cli_rcpt.json"

        active_db_name = str(connection.settings_dict["NAME"])
        with patch("src.services.legal_display_approval.assert_local_environment", return_value=active_db_name):
            with self.assertRaisesRegex(CommandError, "--simulate-revoke"):
                call_command(
                    "manage_legal_display_approval",
                    "--apply",
                    "--simulate-revoke",
                    "--ids",
                    JURIS_ID,
                    stdout=io.StringIO(),
                )

            out = io.StringIO()
            call_command("manage_legal_display_approval", "--check", "--ids", JURIS_ID, stdout=out)
            self.assertEqual(json.loads(out.getvalue())["mode"], "check")

            out = io.StringIO()
            call_command(
                "manage_legal_display_approval",
                "--dry-run",
                "--ids",
                JURIS_ID,
                "--decision-file",
                str(decision),
                stdout=out,
            )
            self.assertTrue(json.loads(out.getvalue())["rolled_back"])

            out = io.StringIO()
            call_command(
                "manage_legal_display_approval",
                "--apply",
                "--ids",
                JURIS_ID,
                "--decision-file",
                str(decision),
                "--snapshot",
                str(snapshot),
                "--receipt",
                str(receipt),
                stdout=out,
            )
            self.assertEqual(json.loads(out.getvalue())["mode"], "apply")

            out = io.StringIO()
            call_command(
                "manage_legal_display_approval",
                "--dry-run",
                "--simulate-revoke",
                "--ids",
                JURIS_ID,
                "--snapshot",
                str(snapshot),
                "--receipt",
                str(receipt),
                stdout=out,
            )
            self.assertEqual(json.loads(out.getvalue())["mode"], "revoke_dry_run")

            out = io.StringIO()
            call_command(
                "manage_legal_display_approval",
                "--revoke",
                "--ids",
                JURIS_ID,
                "--snapshot",
                str(snapshot),
                "--receipt",
                str(receipt),
                stdout=out,
            )
            self.assertEqual(json.loads(out.getvalue())["mode"], "revoke")
