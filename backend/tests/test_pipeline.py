import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase, override_settings

from src.api.datajud_client import DataJudClient, DataJudError
from src.db.models import ExtractionRun, FactProcess, FactProcessSubject, ProcessMovement, RejectedRecord
from src.etl.loader import load_record
from src.etl.transformer import InvalidRecord, normalize, timestamp

SCOPE = {
    "start": "2023-01-01",
    "end": "2025-12-31",
    "end_exclusive": "2026-01-01",
    "subject_codes": [10433, 10439],
    "page_size": 2,
    "court": "TJDFT",
    "origin": "datajud",
}


def hit(identity="synthetic-1", degree="G2"):
    """Synthetic deterministic fixture; never inserted into the local development DB."""
    return {
        "_id": identity,
        "sort": [1700000000000, identity],
        "_source": {
            "id": identity,
            "tribunal": "TJDFT",
            "numeroProcesso": "00000000020238070001",
            "nivelSigilo": 0,
            "grau": degree,
            "dataAjuizamento": "2023-03-30T10:00:00Z",
            "dataHoraUltimaAtualizacao": "2024-01-01T00:00:00Z",
            "@timestamp": "2024-01-02T00:00:00Z",
            "classe": {"codigo": 198, "nome": "Apelação Cível"},
            "orgaoJulgador": {"codigo": 42, "nome": "Synthetic panel", "codigoMunicipioIBGE": 5300108},
            "assuntos": [
                [{"codigo": 10433, "nome": "Indenização por Dano Moral"}],
                {"codigo": 10439, "nome": "Indenização por Dano Material"},
                {"codigo": 10433, "nome": "Indenização por Dano Moral"},
            ],
            "movimentos": [{"codigo": 26, "nome": "Distribuição", "dataHora": "2023-03-30T10:00:00Z"}],
        },
    }


class TransformTests(SimpleTestCase):
    def test_identifiers_nested_subjects_and_duplicate_movements(self):
        source = hit()
        source["_source"]["movimentos"] *= 2
        source["_source"]["unnecessary_personal_field"] = "must not persist"
        record = normalize(source, SCOPE)
        self.assertEqual(record["number_process"], "00000000020238070001")
        self.assertEqual(len(record["subjects"]), 2)
        self.assertEqual(len(record["movements"]), 1)
        self.assertNotIn("unnecessary_personal_field", record["raw"])

    def test_scope_and_privacy_rejections(self):
        for field, value in [
            ("tribunal", "TJSP"),
            ("nivelSigilo", 1),
            ("nivelSigilo", None),
            ("dataAjuizamento", "2022-12-31"),
            ("dataAjuizamento", "invalid"),
            ("numeroProcesso", 123),
            ("grau", "INVALID"),
            ("assuntos", []),
        ]:
            with self.subTest(field=field):
                source = hit()
                source["_source"][field] = value
                with self.assertRaises(InvalidRecord):
                    normalize(source, SCOPE)

    def test_date_formats(self):
        self.assertEqual(timestamp("20230330100000"), timestamp("2023-03-30T10:00:00Z"))
        self.assertEqual(timestamp("2023-03-30T07:00:00-03:00"), timestamp("2023-03-30T10:00:00Z"))


class ClientTests(SimpleTestCase):
    def response(self, hits=None, **extra):
        return io.StringIO(
            json.dumps({"hits": {"hits": hits or [], "total": {"value": 2, "relation": "eq"}}, **extra})
        )

    @patch("src.api.datajud_client.time.sleep")
    @patch("src.api.datajud_client.urlopen")
    def test_query_and_cursor(self, open_url, sleep):
        open_url.return_value = self.response([hit()])
        DataJudClient("synthetic-key").search(SCOPE, [1, "previous"])
        body = json.loads(open_url.call_args.args[0].data)
        self.assertEqual(body["search_after"], [1, "previous"])
        self.assertEqual(body["sort"], [{"@timestamp": "asc"}, {"id.keyword": "asc"}])
        self.assertIn({"term": {"nivelSigilo": 0}}, body["query"]["bool"]["filter"])
        date_filters = body["query"]["bool"]["filter"][2]["bool"]
        self.assertEqual(date_filters["minimum_should_match"], 1)
        self.assertEqual(date_filters["should"][1]["range"]["dataAjuizamento"]["gte"], 20230101000000)

    @patch("src.api.datajud_client.time.sleep")
    @patch("src.api.datajud_client.urlopen")
    def test_retries_and_permanent_http_error(self, open_url, sleep):
        open_url.side_effect = [URLError("offline"), self.response()]
        DataJudClient("synthetic-key").search(SCOPE)
        self.assertEqual(open_url.call_count, 2)
        open_url.reset_mock()
        open_url.side_effect = HTTPError("https://example.test", 401, "unauthorized", {}, None)
        with self.assertRaisesRegex(DataJudError, "401"):
            DataJudClient("synthetic-key").search(SCOPE)
        self.assertEqual(open_url.call_count, 1)

    @patch("src.api.datajud_client.urlopen")
    def test_partial_response_and_stalled_cursor_fail(self, open_url):
        for payload in [
            self.response([hit()], timed_out=True),
            self.response([hit()], _shards={"failed": 1}),
            self.response([hit()]),
        ]:
            open_url.return_value = payload
            with self.assertRaises(DataJudError):
                DataJudClient("synthetic-key").search(SCOPE, hit()["sort"])

    def test_missing_key(self):
        with self.assertRaises(DataJudError):
            DataJudClient("")


class WarehouseTests(TestCase):
    def setUp(self):
        self.run = ExtractionRun.objects.create(scope=SCOPE)

    def test_idempotency_and_updated_subject_bridge(self):
        source = hit()
        self.assertEqual(load_record(normalize(source, SCOPE), self.run), "created")
        self.assertEqual(load_record(normalize(source, SCOPE), self.run), "updated")
        self.assertEqual(FactProcess.objects.count(), 1)
        self.assertEqual(FactProcessSubject.objects.count(), 2)
        self.assertEqual(ProcessMovement.objects.count(), 1)
        source["_source"]["assuntos"] = [{"codigo": 10433, "nome": "Moral"}]
        source["_source"]["movimentos"] = []
        load_record(normalize(source, SCOPE), self.run)
        self.assertEqual(FactProcessSubject.objects.count(), 1)
        self.assertEqual(ProcessMovement.objects.count(), 0)

    def test_older_source_does_not_overwrite(self):
        load_record(normalize(hit(), SCOPE), self.run)
        older = hit()
        older["_source"]["dataHoraUltimaAtualizacao"] = "2023-01-01"
        self.assertEqual(load_record(normalize(older, SCOPE), self.run), "stale")
        self.assertEqual(FactProcess.objects.get().source_updated_at.year, 2024)

    def test_loader_rollback(self):
        with patch.object(ProcessMovement.objects, "bulk_create", side_effect=RuntimeError("simulated")):
            with self.assertRaises(RuntimeError):
                load_record(normalize(hit(), SCOPE), self.run)
        self.assertEqual(FactProcess.objects.count(), 0)
        self.assertEqual(FactProcessSubject.objects.count(), 0)

    def test_bridge_unique_constraint(self):
        load_record(normalize(hit(), SCOPE), self.run)
        bridge = FactProcessSubject.objects.first()
        with self.assertRaises(IntegrityError), transaction.atomic():
            FactProcessSubject.objects.create(process=bridge.process, subject=bridge.subject)

    @override_settings(DATAJUD_API_KEY="synthetic-key")
    @patch("src.db.management.commands.extract_datajud.DataJudClient.search")
    def test_pause_resume_rejections_and_empty_completion(self, search):
        invalid = hit("bad")
        invalid["_source"]["nivelSigilo"] = 1
        search.return_value = {"hits": [hit(), invalid], "total": {"value": 3, "relation": "eq"}}
        call_command(
            "extract_datajud", subjects="10433,10439", end="2025-12-31", max_pages=1, stdout=io.StringIO()
        )
        run = ExtractionRun.objects.latest("id")
        self.assertEqual((run.status, run.fetched, run.created, run.rejected), ("paused", 2, 1, 1))
        self.assertEqual(RejectedRecord.objects.get().source_id, "bad")
        search.side_effect = [
            {"hits": [hit("second")], "total": {"value": 3, "relation": "eq"}},
            {"hits": []},
        ]
        call_command("extract_datajud", resume=run.pk, max_pages=0, stdout=io.StringIO())
        run.refresh_from_db()
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.fetched, 3)
        self.assertEqual(FactProcess.objects.count(), 2)
        self.assertEqual(search.call_args_list[-2].args[1], invalid["sort"])
        with self.assertRaises(CommandError):
            call_command("extract_datajud", resume=run.pk, stdout=io.StringIO())

    @override_settings(DATAJUD_API_KEY="synthetic-key")
    @patch("src.db.management.commands.extract_datajud.DataJudClient.search")
    def test_failed_page_rolls_back_cursor_and_records(self, search):
        search.return_value = {"hits": [hit(), hit("second")]}
        with patch(
            "src.db.management.commands.extract_datajud.load_record",
            side_effect=["created", RuntimeError("simulated")],
        ):
            with self.assertRaises(CommandError):
                call_command("extract_datajud", subjects="10433", stdout=io.StringIO())
        run = ExtractionRun.objects.latest("id")
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.fetched, 0)
        self.assertIsNone(run.cursor)

    def test_offline_import_is_sample_and_no_key_required(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.json"
            path.write_text(json.dumps({"hits": {"hits": [hit()]}}), encoding="utf8")
            call_command("extract_datajud", input=path, subjects="10433", stdout=io.StringIO())
        self.assertEqual(ExtractionRun.objects.latest("id").status, "sample")


class ApiTests(TestCase):
    def setUp(self):
        run = ExtractionRun.objects.create(scope=SCOPE, status="sample")
        load_record(normalize(hit(), SCOPE), run)
        load_record(normalize(hit("another-instance", "G1"), SCOPE), run)

    def test_statistics_do_not_count_subjects_or_infer_outcomes(self):
        data = self.client.get("/api/statistics/").json()
        self.assertEqual(data["metrics"]["process_records"], 2)
        self.assertEqual(data["metrics"]["distinct_process_numbers"], 1)
        self.assertIsNone(data["metrics"]["grant_rate"])
        self.assertIsNone(data["metrics"]["analyzed_appeals"])
        self.assertEqual(
            self.client.get("/api/statistics/?outcome=granted").json()["metrics"], data["metrics"]
        )
        self.assertEqual(
            self.client.get("/api/statistics/?subject=10433").json()["metrics"]["process_records"], 2
        )

    def test_instances_are_volume_by_filing_quarter(self):
        result = self.client.get("/api/instances/").json()
        self.assertEqual([row["count"] for row in result["series"]], [1, 1])
        self.assertTrue(all(row["time__quarter"] == 1 for row in result["series"]))

    def test_scope_and_paginated_processes(self):
        self.assertEqual(len(self.client.get("/api/scope/").json()["subjects"]), 2)
        rows = self.client.get("/api/processes/?page_size=1").json()
        self.assertEqual(rows["count"], 2)
        self.assertEqual(len(rows["results"]), 1)
        self.assertNotIn("raw_payload", rows["results"][0])
        self.assertEqual(self.client.get("/api/processes/?page=3&page_size=1").json()["results"], [])

    def test_invalid_parameters_and_read_only(self):
        for query in [
            "court=TJSP",
            "start=2022-01-01",
            "start=wrong",
            "start=2025-01-01&end=2024-01-01",
            "subject=abc",
            "outcome=maybe",
            "start=2023-01-01&start=2024-01-01",
            "unknown=yes",
        ]:
            with self.subTest(query=query):
                self.assertEqual(self.client.get("/api/statistics/?" + query).status_code, 400)
        self.assertEqual(self.client.get("/api/processes/?page_size=101").status_code, 400)
        self.assertEqual(self.client.post("/api/statistics/").status_code, 405)

    def test_empty_does_not_become_zero_success(self):
        data = self.client.get("/api/statistics/?start=2025-01-01&end=2025-12-31").json()
        self.assertEqual(data["status"], "empty")
        self.assertEqual(data["metrics"]["process_records"], 0)
        self.assertIsNone(data["metrics"]["grant_rate"])
        distribution = self.client.get("/api/distribution/").json()
        self.assertEqual(distribution["status"], "unavailable")
        self.assertEqual(distribution["series"], [])

    def test_cors_and_health(self):
        allowed = self.client.get("/api/health/", HTTP_ORIGIN="http://localhost:5173")
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed["Access-Control-Allow-Origin"], "http://localhost:5173")
        blocked = self.client.get("/api/health/", HTTP_ORIGIN="https://untrusted.example")
        self.assertNotIn("Access-Control-Allow-Origin", blocked)
