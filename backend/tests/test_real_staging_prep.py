"""Isolated synthetic tests for minimized local staging preparation."""

from __future__ import annotations

from datetime import date
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connections
from django.test import TestCase, override_settings

from src.accounts.models import AuditEvent, Court
from src.db.models import (
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
    LegalReference,
    ProcessMovement,
)
from src.db.sampling_models import CivilSampleMember, CivilSamplingCohort
from src.services.real_staging_prep import (
    EXPECTED_COHORT,
    EXPECTED_SOURCE_DATABASE,
    StagingPrepError,
    assert_safe_staging_databases,
    audit_staging_database,
    materialize_minimized_staging,
    sanitize_extraction_scope,
)


class RealStagingPrepTests(TestCase):
    databases = "__all__"
    target_alias = "staging_test_target"

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.target_db_path = Path(cls._tmpdir.name) / "staging_target.sqlite3"
        connections.databases[cls.target_alias] = {
            **connections.databases["default"],
            "NAME": str(cls.target_db_path),
        }
        call_command("migrate", database=cls.target_alias, verbosity=0)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            connections[cls.target_alias].close()
            connections.databases.pop(cls.target_alias, None)
            cls._tmpdir.cleanup()

    def setUp(self):

        # Seed source (default in-memory SQLite) with procedural data + sensitive/excluded tables
        Court.objects.get_or_create(code="STJ", defaults={"name": "STJ"})
        Court.objects.get_or_create(code="TJDFT", defaults={"name": "TJDFT"})

        # Excluded data that MUST NOT reach target
        user = get_user_model().objects.create_user(username="local-admin", role="Admin", approved=True)
        AuditEvent.objects.create(actor=user, action="user.login", target_id=str(user.pk))
        ref = LegalReference.objects.create(
            reference_type="precedent",
            source_institution="STJ",
            identifier="STJ:SUMULA:37",
            title="Súmula sintética",
            thesis="",
            source_name="STJ",
            source_url="https://www.stj.jus.br/",
            approval_reference="DATUMLEX-4D:STJ:SUMULA:37",
            approved=True,
            source_metadata={"permissions": {"display": "allowed"}},
        )
        LegalCorpusItem.objects.create(
            origin_key=f"reference:{ref.pk}",
            category="precedent",
            court="STJ",
            title=ref.title,
            source_name="STJ",
            fingerprint="a" * 64,
            review_status="approved",
            provenance={"reference_id": ref.pk, "permissions": {"display": "allowed"}},
        )

        # Procedural cohort data
        self.cohort = CivilSamplingCohort.objects.create(
            name=EXPECTED_COHORT,
            definition={"start_year": 2010, "target": 325, "subjects": [10433]},
        )
        run = ExtractionRun.objects.create(
            status="completed",
            scope={
                "court": "STJ",
                "start": "2016-01-01",
                "end": "2026-03-31",
                "origin": "datajud_backup_recovery",
                "source_database": "datumlex_backup_review_20261113",
                "source_run_ids": [3],
            },
            cursor={"after": ["secret-cursor"]},
            error="internal stacktrace",
        )
        d_cls = DimClass.objects.create(code=198, name="Recurso Especial")
        d_subj = DimSubject.objects.create(code=10433, name="Indenização por Dano Moral")
        d_deg, _ = DimDegree.objects.get_or_create(code="SUP", defaults={"name": "SUP"})
        d_res, _ = DimResult.objects.get_or_create(name="granted")
        d_time = DimTime.objects.create(date=date(2024, 6, 15), year=2024, month=6, day=15, quarter=2)
        d_org = DimOrg.objects.create(court="STJ", code=10, name="Terceira Turma")
        self.proc = DimProcess.objects.create(number_process="00000010020243000001", secrecy_level=0)

        self.fact = FactProcess.objects.create(
            source_id="STJ:synth-fact-1",
            process_dimension=self.proc,
            court="STJ",
            degree_dimension=d_deg,
            result=d_res,
            time=d_time,
            process_class=d_cls,
            organization=d_org,
            last_run=run,
            raw_payload={"should_be_stripped": True, "nivelSigilo": 0},
            payload_hash="a" * 64,
        )
        FactProcessSubject.objects.create(process=self.fact, subject=d_subj)
        CivilSampleMember.objects.create(
            cohort=self.cohort,
            fact=self.fact,
            process=self.proc,
            court="STJ",
            year=2024,
            filing_month=6,
            subject_code=10433,
            origin="datajud",
        )
        # One outcome-proof movement (kept minimized) + one non-outcome movement (excluded)
        ProcessMovement.objects.create(
            process=self.fact,
            code=12434,
            name="Provimento",
            occurred_at=self.fact.collected_at,
            complements=[{"desc": "sensitive-complement"}],
            fingerprint="b" * 64,
        )
        ProcessMovement.objects.create(
            process=self.fact,
            code=999999,
            name="Movimento irrelevante",
            occurred_at=self.fact.collected_at,
            complements=[{"desc": "ignored"}],
            fingerprint="c" * 64,
        )

    def test_materialize_minimizes_fields_excludes_sensitive_tables_and_preserves_merit(self):
        result = materialize_minimized_staging(
            "default",
            self.target_alias,
            cohort_name=EXPECTED_COHORT,
            allow_test_db=True,
        )
        self.assertEqual(result["publication_status"], "blocked_pending_authorization")
        self.assertEqual(result["staging_audit"]["total_documents"], 1)
        self.assertEqual(result["staging_audit"]["total_distinct_cnjs"], 1)
        self.assertEqual(result["staging_audit"]["merit_binary"]["eligible"], 1)
        self.assertEqual(result["staging_audit"]["merit_binary"]["granted"], 1)

        # Excluded tables strictly 0 on target
        self.assertEqual(get_user_model().objects.using(self.target_alias).count(), 0)
        self.assertEqual(AuditEvent.objects.using(self.target_alias).count(), 0)
        self.assertEqual(LegalReference.objects.using(self.target_alias).count(), 0)
        self.assertEqual(LegalCorpusItem.objects.using(self.target_alias).count(), 0)

        # Minimization verified on target
        copied_fact = FactProcess.objects.using(self.target_alias).get()
        self.assertEqual(copied_fact.raw_payload, {})
        self.assertEqual(copied_fact.process_dimension.number_process, "00000010020243000001")

        # Only outcome-proof movement copied, stripped of name & complements
        mvs = list(ProcessMovement.objects.using(self.target_alias).all())
        self.assertEqual(len(mvs), 1)
        self.assertEqual(mvs[0].code, 12434)
        self.assertEqual(mvs[0].name, "")
        self.assertEqual(mvs[0].complements, [])

        # ExtractionRun stripped of cursor, error, and internal backup names
        copied_run = ExtractionRun.objects.using(self.target_alias).get()
        self.assertIsNone(copied_run.cursor)
        self.assertEqual(copied_run.error, "")
        self.assertNotIn("source_database", copied_run.scope)
        self.assertEqual(copied_run.scope["court"], "STJ")

        # Audit confirms all invariants pass and manifest contains zero CNJs
        audit = audit_staging_database(self.target_alias, cohort_name=EXPECTED_COHORT)
        self.assertTrue(all(audit["invariants"].values()))
        self.assertNotIn("00000010020243000001", str(result))

    def test_secrecy_level_nonzero_fails_closed(self):
        DimProcess.objects.filter(pk=self.proc.pk).update(secrecy_level=1)
        with self.assertRaisesRegex(StagingPrepError, "secrecy_level"):
            materialize_minimized_staging("default", self.target_alias, allow_test_db=True)
        self.assertEqual(FactProcess.objects.using(self.target_alias).count(), 0)

    def test_environment_and_database_guards_fail_closed(self):
        with override_settings(SYNTHETIC_PREVIEW=True):
            with self.assertRaisesRegex(StagingPrepError, "SYNTHETIC_PREVIEW"):
                assert_safe_staging_databases("default", self.target_alias, allow_test_db=True)

        with patch.dict(os.environ, {"RAILWAY_ENVIRONMENT_NAME": "production"}, clear=False):
            with self.assertRaisesRegex(StagingPrepError, "ambiente remoto"):
                assert_safe_staging_databases("default", self.target_alias, allow_test_db=True)

        with self.assertRaisesRegex(StagingPrepError, "mesmo alias"):
            assert_safe_staging_databases("default", "default", allow_test_db=True)

        with self.assertRaisesRegex(StagingPrepError, "PostgreSQL local"):
            assert_safe_staging_databases("default", self.target_alias, allow_test_db=False)

        self.assertEqual(
            sanitize_extraction_scope({"court": "TJDFT", "source_database": "internal_backup", "origin": "datajud"}),
            {"court": "TJDFT", "origin": "datajud"},
        )

        # Mock PostgreSQL connections to verify target naming & operational DB protection
        class FakeConn:
            def __init__(self, host, name):
                self.vendor = "postgresql"
                self.settings_dict = {"HOST": host, "NAME": name}

        fake_conns = {
            "src": FakeConn("127.0.0.1", EXPECTED_SOURCE_DATABASE),
            "bad_same": FakeConn("127.0.0.1", EXPECTED_SOURCE_DATABASE),
            "bad_prefix": FakeConn("127.0.0.1", "datumlex_preview_4f_synthetic"),
            "bad_host": FakeConn("postgres.railway.internal", "datumlex_staging_demo"),
            "good_dst": FakeConn("127.0.0.1", "datumlex_staging_real_civil_2026_11"),
        }
        with patch("src.services.real_staging_prep.connections", fake_conns):
            with self.assertRaisesRegex(StagingPrepError, "banco operacional"):
                assert_safe_staging_databases("src", "bad_same", allow_test_db=False)
            with self.assertRaisesRegex(StagingPrepError, "datumlex_staging_"):
                assert_safe_staging_databases("src", "bad_prefix", allow_test_db=False)
            with self.assertRaisesRegex(StagingPrepError, "loopback"):
                assert_safe_staging_databases("src", "bad_host", allow_test_db=False)
            self.assertEqual(
                assert_safe_staging_databases("src", "good_dst", allow_test_db=False),
                (EXPECTED_SOURCE_DATABASE, "datumlex_staging_real_civil_2026_11"),
            )
