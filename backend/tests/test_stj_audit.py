import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from django.core.management import call_command
from django.test import TestCase, override_settings

from src.db.models import STJDocument, STJDocumentVersion, STJIngestionRun
from src.etl.stj_ingestion import persist_document
from tests.test_stj_documents import collector


class STJAuditTests(TestCase):
    def setUp(self):
        self.run = STJIngestionRun.objects.create(
            scope={}, collector_version="test", catalog_url=collector.CATALOG
        )
        self.row = {"seqDocumento": 123, "dataPublicacao": "2023-01-03", "assuntos": "10433"}

    def persist(self, directory, payload, **changes):
        return persist_document(
            {**self.row, **changes},
            payload,
            ".txt",
            "https://dadosabertos.web.stj.jus.br/meta",
            "https://dadosabertos.web.stj.jus.br/archive",
            directory,
            self.run,
        )

    def test_idempotency_updates_preserve_original_text_and_versions(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            directory = base / "etl" / "data" / "stj-documents"
            self.assertEqual(self.persist(directory, b"first"), ("created", False))
            first_path = STJDocument.objects.get().local_path
            self.assertEqual(self.persist(directory, b"first"), ("duplicates", False))
            self.assertEqual(self.persist(directory, b"second"), ("updated", False))
            self.assertEqual((directory / first_path).read_bytes(), b"first")
            document = STJDocument.objects.get()
            self.assertEqual((directory / document.local_path).read_bytes(), b"second")
            self.assertEqual(document.versions.count(), 2)
            self.assertIsNone(document.panel)
            self.assertIsNone(document.precedent_status)
            self.assertIsNone(document.decision_date)

    def test_unavailable_then_recovered_never_loses_acquired_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.assertEqual(self.persist(directory, None), ("created", True))
            self.assertEqual(STJDocument.objects.get().text_status, "unavailable")
            self.assertEqual(self.persist(directory, b"recovered"), ("updated", False))
            self.assertEqual(self.persist(directory, None), ("duplicates", True))
            self.assertEqual(STJDocument.objects.get().text_status, "available")
            self.assertEqual(STJDocumentVersion.objects.count(), 2)

    def test_explicit_panel_dates_precedent_fields_and_metadata_revision(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.persist(
                directory,
                b"text",
                orgaoJulgador="SEGUNDA SECAO",
                dataJulgamento="2023-01-02",
                tipoPrecedente="source value",
                situacaoPrecedente="source status",
            )
            self.persist(directory, b"text", orgaoJulgador="CORTE ESPECIAL", dataJulgamento="2023-01-02")
            document = STJDocument.objects.get()
            self.assertEqual(document.panel, "CORTE ESPECIAL")
            self.assertEqual(str(document.decision_date), "2023-01-02")
            self.assertEqual(document.versions.count(), 2)

    def test_legacy_baseline_is_hash_verified_and_repeatable(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            directory = base / "etl" / "data" / "stj-documents"
            self.persist(directory, b"legacy")
            STJDocumentVersion.objects.all().delete()
            with override_settings(BASE_DIR=base / "backend"):
                call_command("backfill_stj_lineage", stdout=io.StringIO())
                call_command("backfill_stj_lineage", stdout=io.StringIO())
            self.assertEqual(STJDocumentVersion.objects.count(), 1)
            self.assertEqual(STJIngestionRun.objects.order_by("-pk").first().retrieved, 0)

    def test_report_detects_corruption_and_reconciles_counters(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            directory = base / "etl" / "data" / "stj-documents"
            self.persist(directory, b"text")
            self.run.retrieved = self.run.created = 1
            self.run.save()
            output = io.StringIO()
            (directory / STJDocument.objects.get().local_path).write_bytes(b"corrupt")
            with override_settings(BASE_DIR=base / "backend"):
                call_command("report_stj_ingestion", verify_files=True, stdout=output)
            report = json.loads(output.getvalue())
            self.assertTrue(report["runs"][0]["reconciled"])
            self.assertEqual(report["field_coverage"]["panel"]["unavailable"], 1)
            self.assertEqual(report["file_integrity"]["hash_mismatch"], ["123"])

    @patch.object(collector.time, "sleep")
    @patch.object(collector, "urlopen")
    def test_retry_after_rate_limit_and_no_retry_for_not_found(self, opener, sleep):
        response = io.BytesIO(b"payload")
        response.url = "https://dadosabertos.web.stj.jus.br/resource"
        opener.side_effect = [HTTPError(response.url, 429, "limited", {"Retry-After": "2"}, None), response]
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "download"
            collector.download(response.url, target)
            self.assertEqual(target.read_bytes(), b"payload")
            sleep.assert_any_call(2)
            opener.reset_mock()
            opener.side_effect = HTTPError(response.url, 404, "missing", {}, None)
            with self.assertRaises(HTTPError):
                collector.download(response.url, target)
            self.assertEqual(opener.call_count, 1)
