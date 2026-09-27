import io
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from src.services.deterministic_mapping import map_record

EXAMPLES = Path(__file__).parent / "fixtures" / "mapping"


class DeterministicMappingTests(SimpleTestCase):
    def setUp(self):
        self.rules = json.loads((EXAMPLES / "rules.json").read_text(encoding="utf-8"))
        self.records = json.loads((EXAMPLES / "records.json").read_text(encoding="utf-8"))

    def test_reviewable_examples_and_provenance(self):
        expected = [
            ("complete", "synthetic_allowed"),
            ("partial", "synthetic_allowed"),
            ("unknown", None),
            ("conflict", None),
        ]
        for index, (record, (status, target)) in enumerate(zip(self.records, expected, strict=True)):
            with self.subTest(status=status):
                result = map_record(record, self.rules, {"file": "records.json", "json_pointer": f"/{index}"})
                self.assertEqual((result["status"], result["target"]), (status, target))
                self.assertEqual(result["rule_version"], "synthetic-example-v1")
                self.assertEqual(len(result["rules_sha256"]), 64)
                self.assertEqual(result["evidence"]["input"]["json_pointer"], f"/{index}")
                if status != "unknown":
                    self.assertTrue(result["evidence"]["matches"][0]["references"])

    def test_no_fuzzy_matching_and_type_coercion(self):
        result = map_record({"code": "900001", "name": "synthetic allowed"}, self.rules, {"file": "test"})
        self.assertEqual(result["status"], "unknown")

    def test_ambiguous_rules_do_not_choose_first(self):
        other = {**self.rules["rules"][0], "id": "collision", "target": "different"}
        self.rules["rules"].append(other)
        result = map_record(self.records[0], self.rules, {"file": "test"})
        self.assertEqual(result["status"], "conflict")
        self.assertIsNone(result["target"])

    def test_rule_order_does_not_change_decision(self):
        first = map_record(self.records[3], self.rules, {"file": "test"})
        self.rules["rules"].reverse()
        second = map_record(self.records[3], self.rules, {"file": "test"})
        for key in ("status", "target", "candidates", "evidence"):
            self.assertEqual(first[key], second[key])

    def test_rejects_missing_version_or_evidence(self):
        for key in ("rule_version", "evidence"):
            rules = json.loads(json.dumps(self.rules))
            del (rules if key == "rule_version" else rules["rules"][0])[key]
            with self.assertRaises(ValueError):
                map_record(self.records[0], rules, {"file": "test"})

    def test_persists_snapshot_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            options = {
                "input": EXAMPLES / "records.json",
                "rules": EXAMPLES / "rules.json",
                "output": output,
                "stdout": io.StringIO(),
            }
            call_command("map_records", **options)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["rules"], self.rules)
            self.assertEqual(
                [r["status"] for r in report["results"]], ["complete", "partial", "unknown", "conflict"]
            )
            before = output.read_bytes()
            with self.assertRaises(CommandError):
                call_command("map_records", **options)
            self.assertEqual(output.read_bytes(), before)
