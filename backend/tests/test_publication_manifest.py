import json
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from django.core.management import CommandError
from django.test import SimpleTestCase

from src.db.civil_subjects import CATALOG
from src.db.management.commands.validate_civil_publication import Command
from src.db.models import ProcessMovement
from src.services.publication_manifest import (
    build_cohort_manifest, build_manifest, canonical_bytes, digest, validate_cell, verify_rollback,
)


class PublicationManifestTests(SimpleTestCase):
    def setUp(self):
        self.definition = {"subjects": [10431, 10433], "sgt_version": CATALOG["version"],
                           "target": 2, "start_year": 2010, "seed": "synthetic-seed"}
        timestamp = datetime(2023, 9, 1, tzinfo=timezone.utc)
        self.tables = {
            "warehouse_civilsamplingcohort": {1: {"id": 1, "definition": self.definition}},
            "warehouse_civilsamplemember": {1: {
                "id": 1, "cohort_id": 1, "fact_id": 1, "process_id": 1, "court": "TJDFT",
                "year": 2023, "filing_month": 2, "subject_code": 10433,
            }},
            "fact_resource": {1: {
                "id": 1, "court": "TJDFT", "process_dimension_id": 1, "time_id": 1,
                "process_class_id": 1, "degree_dimension_id": 1, "result_id": 1, "organization_id": 1,
                "last_run_id": 1, "source_id": "synthetic-datajud-id", "payload_hash": "a" * 64,
                "quant_process": 1, "collected_at": timestamp,
            }},
            "accounts_court": {1: {"id": 1, "code": "TJDFT"}},
            "dim_process": {1: {"id": 1, "number_process": "1" * 20, "secrecy_level": 0}},
            "dim_time": {1: {"id": 1, "date": date(2023, 2, 1), "year": 2023, "month": 2, "quarter": 1}},
            "dim_class": {1: {"id": 1, "name": "Classe de teste"}},
            "dim_degree": {1: {"id": 1, "code": "G2"}},
            "dim_result": {1: {"id": 1, "name": "denied"}},
            "dim_org": {1: {"id": 1, "court": "TJDFT"}},
            "extraction_run": {1: {"id": 1, "status": "completed"}},
            "dim_subject": {1: {"id": 1, "code": 10433}},
            "fact_process_subject": {1: {"id": 1, "process_id": 1, "subject_id": 1}},
        }
        self.movements = {1: [
            ProcessMovement(id=99, process_id=1, code=239, occurred_at=timestamp, fingerprint="b" * 64),
            ProcessMovement(id=12, process_id=1, code=237, occurred_at=timestamp, fingerprint="c" * 64),
        ]}
        self.collection = json.loads(Path(__file__).with_name("fixtures").joinpath(
            "publication_collection_synthetic.json"
        ).read_text(encoding="utf-8"))

    def receipt(self, collection=None):
        return build_manifest("example", "TJDFT", 2023, self.definition, self.tables, self.movements, collection)

    def test_manifest_is_deterministic_aggregate_and_keeps_partial_blocked(self):
        first = self.receipt(self.collection)
        self.movements[1].reverse()
        self.collection["evidence"].reverse()
        self.tables = dict(reversed(list(self.tables.items())))
        second = self.receipt(self.collection)
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        serialized = canonical_bytes(first)
        self.assertNotIn(b"11111111111111111111", serialized)
        self.assertNotIn(b"synthetic-datajud-id", serialized)
        self.assertNotIn(b"trecho jur", serialized)
        body = first["manifest"]
        self.assertEqual(first["sha256"], digest(body))
        self.assertEqual(body["coverage"]["gap"], 1)
        self.assertEqual(body["validation"]["status"], "passed")
        self.assertEqual(body["publication"]["status"], "blocked")
        self.assertIn("partial_cell", body["publication"]["reasons"])

    def test_materialized_result_uses_original_movement_id_to_break_tie(self):
        result = validate_cell(self.tables, self.movements, "TJDFT", date(2023, 1, 1), date(2023, 12, 31), {10433})
        self.assertEqual(result["proofs"][1]["movement_id"], 99)
        self.assertEqual(result["outcome_ties"], 1)
        manifest = self.receipt()["manifest"]
        self.assertEqual(manifest["indicators"]["binary_denominator"], 1)
        self.assertEqual(manifest["indicators"]["outcomes"], {"denied": 1})
        self.assertEqual(manifest["indicators"]["series"], [{"quarter": 1, "degree": "G2", "count": 1}])
        self.tables["dim_result"][1]["name"] = "granted"
        invalid = self.receipt()["manifest"]
        self.assertEqual(invalid["validation"]["errors"], {"outcome_mismatch": 1})
        self.assertEqual(invalid["publication"]["status"], "blocked")

    def test_dependencies_and_uniqueness_fail_closed(self):
        for table in ("extraction_run", "dim_subject", "warehouse_civilsamplingcohort", "fact_resource"):
            with self.subTest(table=table):
                saved = self.tables[table].pop(1)
                result = self.receipt()["manifest"]
                self.assertEqual(result["validation"]["status"], "failed")
                self.assertEqual(result["validation"]["suspended_members"], 1)
                self.tables[table][1] = saved
        members = self.tables["warehouse_civilsamplemember"]
        members[2] = {**members[1], "id": 2}
        result = self.receipt()["manifest"]
        self.assertEqual(result["coverage"]["gap"], 0)
        self.assertEqual(result["validation"]["suspension_reasons"], {"duplicate_member": 2})
        self.assertIn("validation_failed", result["publication"]["reasons"])

    def test_lost_eligibility_is_identified_without_exposing_case_identity(self):
        self.tables["dim_process"][1]["secrecy_level"] = 1
        self.tables["dim_org"][1]["court"] = "STJ"
        self.tables["dim_subject"][1]["code"] = 20
        self.tables["dim_time"][1]["date"] = date(2022, 2, 1)
        result = validate_cell(self.tables, self.movements, "TJDFT", date(2023, 1, 1), date(2023, 12, 31), {10433})
        self.assertEqual(result["suspensions"], {1: ["court", "filing_period", "public_process", "subject"]})
        manifest = self.receipt()["manifest"]
        self.assertEqual(manifest["validation"]["suspended_members"], 1)
        self.assertNotIn("suspensions", manifest["validation"])

    def test_full_unverified_cell_remains_blocked(self):
        self.definition["target"] = 1
        body = self.receipt()["manifest"]
        self.assertEqual(body["coverage"]["state"], "unverified")
        self.assertEqual(body["publication"], {"status": "blocked", "reasons": ["coverage_unverified"]})

    def test_consolidation_keeps_cross_cell_occurrences_and_deduplicates_dependencies(self):
        members, facts = self.tables["warehouse_civilsamplemember"], self.tables["fact_resource"]
        members[2] = {**members[1], "id": 2, "fact_id": 2, "year": 2024}
        facts[2] = {**facts[1], "id": 2, "source_id": "synthetic-second-fact", "time_id": 2}
        times = self.tables["dim_time"]
        times[2] = {**times[1], "id": 2, "date": date(2024, 2, 1), "year": 2024}
        self.tables["fact_process_subject"][2] = {"id": 2, "process_id": 2, "subject_id": 1}
        self.movements[2] = [ProcessMovement(id=199, process_id=2, code=239,
                                            occurred_at=self.movements[1][0].occurred_at, fingerprint="d" * 64)]
        receipt, proofs = build_cohort_manifest("example", date(2024, 12, 31), self.definition, self.tables, self.movements)
        body = receipt["manifest"]
        self.assertEqual(body["counts"], {"members": 2, "facts": 2, "distinct_cnj": 1, "cell_occurrences": 2})
        self.assertEqual(body["snapshot"]["tables"]["dim_process"]["rows"], 1)
        self.assertEqual(body["coverage"]["observed_cells"], 2)
        self.assertEqual(body["indicators"]["binary_denominator"], 2)
        self.assertEqual(set(proofs), {1, 2})
        self.assertTrue(all(c["source_exhaustion"] == "unverified" for c in body["coverage"]["cells"]))
        self.assertEqual(body["validation"]["status"], "passed")

    def test_consolidation_blocks_revoked_and_out_of_scope_members(self):
        revoked = {"1" * 20}
        receipt, _ = build_cohort_manifest("example", date(2023, 12, 31), self.definition, self.tables,
                                          self.movements, revoked)
        self.assertEqual(receipt["manifest"]["validation"]["suspension_reasons"], {"revoked": 1})
        self.assertEqual(receipt["manifest"]["validation"]["status"], "failed")
        self.tables["warehouse_civilsamplemember"][1]["year"] = 2024
        receipt, _ = build_cohort_manifest("example", date(2023, 12, 31), self.definition, self.tables, self.movements)
        self.assertEqual(receipt["manifest"]["validation"]["suspension_reasons"], {"outside_scope": 1})
        self.assertEqual(receipt["manifest"]["publication"]["status"], "blocked")

    def test_rollback_requires_pinned_hash_and_matching_projected_data(self):
        previous = self.receipt(self.collection)
        self.assertTrue(verify_rollback(self.receipt(self.collection), previous, previous["sha256"]))
        self.assertFalse(verify_rollback(self.receipt(self.collection), previous, "f" * 64))
        tampered = deepcopy(previous)
        tampered["manifest"]["snapshot"]["tables"]["dim_class"]["sha256"] = "f" * 64
        self.assertFalse(verify_rollback(self.receipt(self.collection), tampered, previous["sha256"]))
        self.tables["dim_class"][1]["name"] = "Conteúdo alterado, coorte igual"
        self.assertFalse(verify_rollback(self.receipt(self.collection), previous, previous["sha256"]))
        self.tables["dim_class"][1]["name"] = "Classe de teste"
        self.tables["dim_process"][1]["secrecy_level"] = 1
        self.assertFalse(verify_rollback(self.receipt(self.collection), previous, previous["sha256"]))

    def test_independent_collection_preserves_candidates_and_all_three_categories(self):
        for category in ("precedent", "doctrine"):
            item = {**self.collection["items"][0], "id": category, "category": category, "reference_id": category,
                    "evidence_ids": [], "text_version_id": None, "subject_codes": [], "tpu_required": False}
            self.collection["items"].append(item)
            self.collection["references"].append({key: item[key] for key in (
                "id", "category", "source_url", "source_locator", "review_status",
            )})
        body = self.receipt(self.collection)["manifest"]
        self.assertEqual(body["validation"]["status"], "passed")
        self.assertEqual(body["collection"]["categories"], {"jurisprudence": 1, "precedent": 1, "doctrine": 1})
        self.assertEqual(body["collection"]["evidence_review"], {"approved": 1, "candidate": 1})
        self.assertEqual(body["collection"]["selected_evidence"], 1)
        self.assertIn("synthetic_collection", body["publication"]["reasons"])

    def test_invalid_legal_sources_references_tpu_and_provenance_are_rejected(self):
        cases = (
            ("items", "reference_id", "missing", "source_reference"),
            ("items", "review_status", "pending", "source_approval"),
            ("items", "subject_codes", [], "source_tpu"),
            ("items", "text_version_id", "missing", "text_provenance"),
            ("items", "evidence_ids", ["candidate-example"], "evidence_reference"),
            ("text_versions", "subject_codes", [10439], "text_tpu"),
            ("text_versions", "sha256", "f" * 64, "text_hash"),
            ("text_versions", "rights", "pending", "text_provenance"),
            ("evidence", "end", 10000, "evidence_provenance"),
        )
        for group, field, value, error in cases:
            with self.subTest(group=group, field=field):
                collection = deepcopy(self.collection)
                collection[group][0][field] = value
                invalid = self.receipt(collection)["manifest"]
                self.assertIn(error, invalid["validation"]["errors"])
                self.assertEqual(invalid["publication"]["status"], "blocked")

    def test_command_rejects_remote_connection_before_querying(self):
        connection = Mock(vendor="postgresql", settings_dict={"HOST": "remote.example.test"})
        with patch("src.db.management.commands.validate_civil_publication.connections", {"default": connection}):
            with self.assertRaisesMessage(CommandError, "PostgreSQL no computador local"):
                Command().handle(cohort="example", court="TJDFT", year=2023, through=None,
                                 previous_manifest=None, previous_digest=None, collection=None)
        connection.cursor.assert_not_called()
