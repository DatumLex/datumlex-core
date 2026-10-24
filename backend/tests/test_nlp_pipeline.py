"""Engineering regressions only; synthetic fixtures are not legal gold data."""

import json
import tempfile
import unittest
from pathlib import Path

from src.nlp.adapters import SourceProblem, read_source
from src.nlp.contracts import bytes_hash, validate_result
from src.nlp.extraction import annotation, extract, replay_predictions
from src.nlp.journal import Journal
from src.nlp.pipeline import process


class LegalNLPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.journal = Journal(self.root / "journal.db")
        self.addCleanup(self.journal.close)
        self.manifest = {"schema_version": "0.1.0", "parameters": {"short_threshold": 200, "max_paragraph": 6000}}

    def source(self, text="A responsabilidade civil depende do nexo causal, pois o dano deve ser demonstrado."):
        raw = text.encode("utf-8")
        (self.root / "source.txt").write_bytes(raw)
        return {"document_id": "STJ:synthetic", "court": "STJ", "source_version": bytes_hash(raw),
                "artifact_path": "source.txt", "artifact_sha256": bytes_hash(raw),
                "text_sha256": bytes_hash(raw), "source_text": text}

    def test_unicode_crlf_exact_spans(self):
        text = "😀\r\nNão há dano moral."
        item = annotation(text, ["LEGAL_THESIS"], [(3, len(text), text[3:])], "test")
        self.assertEqual(item["segments"][0]["start"], 3)
        row = self.source(text)
        self.assertEqual(read_source(row, self.root), text)

    def test_invented_quote_rejected(self):
        good, rejected = replay_predictions("Não há dano.", [{"labels": ["LEGAL_THESIS"],
            "segments": [{"start": 0, "end": 12, "text": "Sim há dano."}]}])
        self.assertEqual(good, [])
        self.assertEqual(len(rejected), 1)

    def test_invalid_boolean_and_negative_offsets(self):
        for start in (True, -1):
            with self.subTest(start=start), self.assertRaises(ValueError):
                annotation("abc", ["LEGAL_THESIS"], [(start, 3, "abc")], "test")

    def test_unknown_label_rejected(self):
        with self.assertRaises(ValueError):
            annotation("abc", ["WINNER"], [(0, 3, "abc")], "test")

    def test_discontinuous_segments_and_order(self):
        item = annotation("abc def", ["LEGAL_GROUND"], [(0, 3, "abc"), (4, 7, "def")], "test")
        self.assertEqual(len(item["segments"]), 2)
        with self.assertRaises(ValueError):
            annotation("abc def", ["LEGAL_GROUND"], [(4, 7, "def"), (0, 3, "abc")], "test")

    def test_citation_is_not_adoption(self):
        annotations, _ = extract("Súmula 7 do STJ. REsp 1.234/DF. Lei 10.406/2002.")
        self.assertEqual(len(annotations), 3)
        for item in annotations:
            self.assertEqual(item["authority"]["resolution_status"], "unresolved")
            self.assertEqual(item["context"]["adoption"]["value_status"], "unknown")

    def test_thesis_ground_candidates_keep_negation(self):
        text = "A responsabilidade civil não depende de culpa, pois o regime exige dano."
        items, _ = extract(text)
        self.assertEqual({a["labels"][0] for a in items}, {"LEGAL_THESIS", "LEGAL_GROUND"})
        self.assertTrue(all(a["segments"][0]["text"] == text for a in items))
        self.assertTrue(all(a["label_status"] == "proposed" for a in items))

    def test_long_paragraph_is_explicit_partial(self):
        row = self.source("A responsabilidade civil depende de culpa. " * 200)
        result, _ = process(row, self.root, self.manifest, self.journal)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["coverage"]["semantic_skipped_intervals"])

    def test_missing_text_not_negative_prediction(self):
        result, _ = process(self.source(""), self.root, self.manifest, self.journal)
        self.assertEqual(result["status"], "missing_text")
        self.assertEqual(result["annotations"], [])

    def test_invalid_encoding_is_document_failure(self):
        row = self.source()
        raw = b"\xff"
        (self.root / "source.txt").write_bytes(raw)
        row["artifact_sha256"] = bytes_hash(raw)
        result, _ = process(row, self.root, self.manifest, self.journal)
        self.assertEqual(result["status"], "failed")

    def test_resume_is_identical_and_short_text_warned(self):
        row = self.source()
        first, cached = process(row, self.root, self.manifest, self.journal)
        second, resumed = process(row, self.root, self.manifest, self.journal)
        self.assertFalse(cached)
        self.assertTrue(resumed)
        self.assertEqual(first, second)
        self.assertIn("short_text", first["warnings"])
        validate_result(first, row["source_text"])

    def test_changed_source_detected_even_when_cached(self):
        row = self.source()
        process(row, self.root, self.manifest, self.journal)
        (self.root / "source.txt").write_bytes(b"changed")
        result, cached = process(row, self.root, self.manifest, self.journal)
        self.assertFalse(cached)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"][0]["reason"], "artifact_hash_mismatch")

    def test_failed_document_recovers_and_others_continue(self):
        row = self.source()
        raw = (self.root / "source.txt").read_bytes()
        (self.root / "source.txt").unlink()
        failed, _ = process(row, self.root, self.manifest, self.journal)
        (self.root / "source.txt").write_bytes(raw)
        recovered, _ = process(row, self.root, self.manifest, self.journal)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(self.journal.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 2)

    def test_changed_rule_version_creates_new_result(self):
        row = self.source()
        first, _ = process(row, self.root, self.manifest, self.journal)
        other = {**self.manifest, "rules_version": "new"}
        second, cached = process(row, self.root, other, self.journal)
        self.assertFalse(cached)
        self.assertNotEqual(first["job_key"], second["job_key"])

    def test_model_replay_hash_must_match(self):
        row = self.source()
        record = {"document_id": row["document_id"], "text_sha256": "wrong", "annotations": []}
        result, _ = process(row, self.root, self.manifest, self.journal, record)
        self.assertEqual(result["status"], "failed")

    def test_model_valid_and_invalid_proposals_are_separated(self):
        row = self.source("Não houve dano.")
        record = {"document_id": row["document_id"], "text_sha256": row["text_sha256"], "annotations": [
            {"labels": ["CASE_HOLDING"], "segments": [{"start": 0, "end": 15, "text": "Não houve dano."}]},
            {"labels": ["CASE_HOLDING"], "segments": [{"start": 0, "end": 15, "text": "Houve dano."}]},
        ]}
        result, _ = process(row, self.root, self.manifest, self.journal, record)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["annotations"]), 1)
        self.assertEqual(len(result["rejected_candidates"]), 1)

    def test_tjdft_field_identity_and_snapshot(self):
        text = "Não houve dano.\r\n"
        raw = json.dumps({"registros": [{"uuid": "fixture", "segredoJustica": False,
                                        "inteiroTeor": text, "inteiroTeorHtml": "<p>other</p>"}]}).encode()
        (self.root / "tjdft.json").write_bytes(raw)
        row = {"document_id": "TJDFT:fixture", "court": "TJDFT", "text_field": "inteiroTeor",
               "artifact_path": "tjdft.json", "artifact_sha256": bytes_hash(raw),
               "text_sha256": bytes_hash(text.encode())}
        self.assertEqual(read_source(row, self.root), text)
        row["text_field"] = "inteiroTeorHtml"
        with self.assertRaises(SourceProblem):
            read_source(row, self.root)

    def test_artifact_path_cannot_escape_root(self):
        row = self.source()
        row["artifact_path"] = "../outside.txt"
        with self.assertRaisesRegex(SourceProblem, "outside_workspace"):
            read_source(row, self.root)


if __name__ == "__main__":
    unittest.main()
