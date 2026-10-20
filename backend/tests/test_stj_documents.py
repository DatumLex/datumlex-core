import importlib.util
import tempfile
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from src.db.models import FactProcess, STJDocument, STJDocumentBatch

spec = importlib.util.spec_from_file_location(
    "stj_documents", Path(__file__).resolve().parents[2] / "etl" / "stj_documents.py"
)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class DocumentCollectionTests(TestCase):
    def test_publication_subject_filter_safe_paths_and_resume(self):
        base = "https://dadosabertos.web.stj.jus.br/"
        catalog = {
            "success": True,
            "result": {
                "resources": [
                    {"url": base + "metadados20230103.json"},
                    {"url": base + "20230103.zip"},
                ]
            },
        }
        timestamp = int(datetime(2023, 1, 3, 12, tzinfo=timezone.utc).timestamp() * 1000)
        rows = [
            {"seqDocumento": 123, "dataPublicacao": timestamp, "assuntos": "10433;10439"},
            {"seqDocumento": 456, "dataPublicacao": timestamp, "assuntos": "99999"},
        ]
        args = SimpleNamespace(
            start=date(2023, 1, 1), end=date(2023, 1, 5), subjects=["10433"], max_batches=0
        )

        def archive(url, path):
            with zipfile.ZipFile(path, "w") as zipped:
                zipped.writestr("../../123.txt", "Synthetic full text")
                zipped.writestr("20230103/456.txt", "Unrelated subject")

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "texts").mkdir()
            with (
                patch.object(collector, "read_json", side_effect=[catalog, rows]),
                patch.object(collector, "download", side_effect=archive),
            ):
                collector.run(args, directory)
            self.assertEqual(
                (directory / STJDocument.objects.get().local_path).read_text(), "Synthetic full text"
            )
            self.assertFalse((directory / "texts/456.txt").exists())
            with patch.object(collector, "read_json", return_value=catalog) as reader:
                collector.run(args, directory)
                self.assertEqual(reader.call_count, 1)
        self.assertEqual(STJDocument.objects.count(), 1)
        self.assertEqual(STJDocumentBatch.objects.count(), 1)
        self.assertEqual(FactProcess.objects.count(), 0)

    def test_missing_text_does_not_mark_batch_completed(self):
        base = "https://dadosabertos.web.stj.jus.br/"
        catalog = {
            "success": True,
            "result": {
                "resources": [
                    {"url": base + "metadados20230103.json"},
                    {"url": base + "textos20230103.zip"},
                ]
            },
        }
        args = SimpleNamespace(
            start=date(2023, 1, 1), end=date(2023, 1, 5), subjects=["10433"], max_batches=0
        )
        rows = [{"seqDocumento": 123, "dataPublicacao": "2023-01-03", "assuntos": "10433"}]

        def archive(url, path):
            with zipfile.ZipFile(path, "w"):
                pass

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(collector, "read_json", side_effect=[catalog, rows]),
            patch.object(collector, "download", side_effect=archive),
        ):
            collector.run(args, Path(temporary))
        self.assertEqual(STJDocumentBatch.objects.get().scope["missing_document_ids"], ["123"])
