import io
import json
from unittest.mock import patch

from django.core.management import call_command
from django.http import QueryDict
from django.test import TestCase
from src.api.datajud_client import DataJudClient, DataJudError
from src.db.models import ExtractionRun, FactProcess
from src.etl.loader import load_record
from src.etl.transformer import InvalidRecord, normalize
from src.services.statistics_service import filtered_processes, metadata

from tests.test_pipeline import SCOPE, hit


class STJTests(TestCase):
    def test_courts_keep_identity_organizations_and_queries_separate(self):
        local_run = ExtractionRun.objects.create(scope=SCOPE)
        load_record(normalize(hit(), SCOPE), local_run)
        scope = {**SCOPE, "court": "STJ"}
        source = hit(degree="SUP")
        source["_source"]["tribunal"] = "STJ"
        stj_run = ExtractionRun.objects.create(scope=scope)
        load_record(normalize(source, scope), stj_run)
        load_record(normalize(source, scope), stj_run)
        self.assertEqual(FactProcess.objects.count(), 2)
        stj = FactProcess.objects.get(court="STJ")
        self.assertEqual(stj.organization.court, "STJ")
        self.assertEqual(stj.result.name, "outside_degree")
        for court, run in [("TJDFT", local_run), ("STJ", stj_run)]:
            query, selected = filtered_processes(QueryDict(f"court={court}"))
            self.assertEqual(query.count(), 1)
            self.assertEqual(metadata(query, selected)["latest_run"]["id"], run.pk)
        with self.assertRaises(InvalidRecord):
            normalize(source, SCOPE)

    @patch("src.api.datajud_client.time.sleep")
    @patch("src.api.datajud_client.urlopen")
    def test_official_endpoint_and_unsupported_court(self, opener, sleep):
        opener.return_value = io.StringIO(
            json.dumps({"hits": {"hits": [], "total": {"value": 0, "relation": "eq"}}})
        )
        DataJudClient("synthetic-key").search({**SCOPE, "court": "STJ"})
        self.assertEqual(
            opener.call_args.args[0].full_url,
            "https://api-publica.datajud.cnj.jus.br/api_publica_stj/_search",
        )
        with self.assertRaises(DataJudError):
            DataJudClient("synthetic-key").search({**SCOPE, "court": "INVALID"})

    def test_offline_command_accepts_stj_scope(self):
        import tempfile
        from pathlib import Path

        source = hit(degree="SUP")
        source["_source"]["tribunal"] = "STJ"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stj.json"
            path.write_text(json.dumps({"hits": {"hits": [source]}}))
            call_command(
                "extract_datajud",
                court="STJ",
                input=path,
                subjects="10433",
                end="2025-12-31",
                stdout=io.StringIO(),
            )
        self.assertEqual(FactProcess.objects.get().court, "STJ")
