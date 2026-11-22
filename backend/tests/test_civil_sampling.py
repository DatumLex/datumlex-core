import io
import json
from datetime import date
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from src.db.civil_subjects import ROOT, branch_codes, primary_subject
from src.db.models import ExtractionRun, FactProcess
from src.db.sampling_models import CivilSampleMember
from src.etl.civil_sampling import Candidate, choose
from src.etl.loader import load_record
from src.etl.transformer import normalize
from tests.test_pipeline import SCOPE, hit


class CivilAllocationTests(SimpleTestCase):
    def test_hierarchy_and_stratification_reproducible_with_duplicates(self):
        self.assertTrue({ROOT, 10433, 10439}.issubset(branch_codes(ROOT)))
        self.assertNotIn(10439, branch_codes(10433))
        self.assertEqual(primary_subject({10431, 10433}), 10433)
        candidates = [
            Candidate(str(index), 1 if index > 2 else 2, 10433 if index % 2 else 10439, str(index))
            for index in range(1, 17)
        ] + [Candidate("1", 2, 10433, "duplicate")]
        selected = choose(candidates, 4, "fixture")
        self.assertEqual(choose(reversed(candidates), 4, "fixture"), selected)
        self.assertEqual(len(set(item.number for item in selected)), 4)
        self.assertEqual(sum(item.month == 2 for item in selected), 2)
        self.assertFalse({item.number for item in selected} & {
            item.number for item in choose(candidates, 3, "fixture", selected)
        })


class CivilSamplingCommandTests(TestCase):
    def sample(self, **options):
        out = io.StringIO()
        call_command(
            "sample_civil_datajud", courts=["TJDFT"], start_year=2023,
            end=date(2023, 3, 31), stdout=out, **options,
        )
        return json.loads(out.getvalue())

    def test_reuse_unique_processes_with_a_stable_quota(self):
        run = ExtractionRun.objects.create(scope=SCOPE)
        for i, number in enumerate(("00000000020238070001", "00000000020238070001", "00000000020238070002")):
            record = hit(f"sample-{i}")
            record["_source"]["numeroProcesso"] = number
            load_record(normalize(record, SCOPE), run)

        preview = self.sample(target=1)
        self.assertEqual(preview["existing_eligible"], 2)
        self.assertEqual(preview["total"], 1)
        self.assertEqual(CivilSampleMember.objects.count(), 0)
        result = self.sample(target=1, apply=True)
        self.assertEqual(result["selected_from_warehouse"], 1)
        original = CivilSampleMember.objects.get()
        retry = self.sample(target=1, apply=True)
        self.assertEqual(retry["previous_members"], 1)
        self.assertEqual(retry["selected_from_warehouse"], 0)
        self.assertEqual(CivilSampleMember.objects.get().pk, original.pk)
        self.assertEqual(FactProcess.objects.count(), 3)
        with self.assertRaises(CommandError):
            self.sample(target=2, apply=True)

    @override_settings(DATAJUD_API_KEY="fixture-public-key")
    @patch("src.api.datajud_client.DataJudClient.search")
    def test_remote_fills_only_missing_slots_and_records_provenance(self, search):
        result = hit("new-sample")
        result["sort"] = [1, "new-sample"]
        search.side_effect = [{"hits": []}, {"hits": []}, {"hits": [result]}]
        report = self.sample(target=1, fetch=True, apply=True)
        self.assertEqual(search.call_count, 3)
        self.assertEqual(report["remote_scan"]["pages"], 3)
        self.assertEqual(report["new_from_datajud"], 1)
        self.assertEqual(report["gap"], 0)
        self.assertEqual(CivilSampleMember.objects.get().origin, "datajud")
        self.assertEqual(ExtractionRun.objects.get().scope["year"], 2023)
