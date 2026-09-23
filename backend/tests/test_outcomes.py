from datetime import datetime, timezone
from types import SimpleNamespace

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from src.db.models import ExtractionRun, FactProcess
from src.etl.loader import load_record
from src.etl.transformer import normalize
from src.services.outcomes import classify, summarize
from tests.test_pipeline import SCOPE, hit


class OutcomeTests(TestCase):
    def test_summary_deduplicates_subject_joins_and_refreshes_after_import(self):
        run = ExtractionRun.objects.create(scope=SCOPE)
        source = hit()
        source["_source"]["movimentos"] = [
            {"codigo": 237, "nome": "Synthetic", "dataHora": "2024-01-01T00:00:00Z"}
        ]
        load_record(normalize(source, SCOPE), run)
        query = FactProcess.objects.filter(subjects__code__in=[10433, 10439])
        with self.assertNumQueries(1):
            summary = summarize(query)
        self.assertEqual(summary["granted"], 1)
        self.assertEqual(summary["binary_denominator"], 1)
        source["_source"]["movimentos"] = []
        load_record(normalize(source, SCOPE), run)
        updated = summarize(query)
        self.assertEqual(updated["granted"], 0)
        self.assertIsNone(updated["grant_rate"])
        self.assertEqual(updated["excluded"]["unknown"], 1)

    def test_dashboard_queries_do_not_read_payloads_or_movements(self):
        run = ExtractionRun.objects.create(scope=SCOPE)
        load_record(normalize(hit(), SCOPE), run)
        for endpoint in ("scope", "statistics", "distribution", "instances"):
            with self.subTest(endpoint=endpoint), CaptureQueriesContext(connection) as queries:
                response = self.client.get(f"/api/{endpoint}/?subject=10433")
                self.assertEqual(response.status_code, 200)
            sql = " ".join(query["sql"].lower() for query in queries)
            self.assertNotIn("raw_payload", sql)
            self.assertNotIn("process_movement", sql)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get("/api/processes/?page_size=1")
        self.assertEqual(response.status_code, 200)
        sql = " ".join(query["sql"].lower() for query in queries)
        self.assertNotIn("raw_payload", sql)
        self.assertNotIn("complements", sql)

    def test_latest_outcome_ignores_list_order_and_later_unrelated_movements(self):
        def movement(code, day):
            return SimpleNamespace(pk=day, code=code, occurred_at=datetime(2024, 1, day, tzinfo=timezone.utc))

        rows = [movement(237, 2), movement(239, 1), movement(26, 3)]
        process = SimpleNamespace(degree="G2", movements=SimpleNamespace(all=lambda: rows))
        self.assertEqual(classify(process)["outcome"], "granted")
        self.assertEqual(classify(process)["selected_evidence"][0]["code"], 237)
        rows.append(movement(238, 4))
        self.assertEqual(classify(process)["outcome"], "partial")

    def test_equal_dates_use_highest_movement_id_not_iteration_order(self):
        date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        rows = [
            SimpleNamespace(pk=20, code=237, occurred_at=date),
            SimpleNamespace(pk=10, code=239, occurred_at=date),
        ]
        process = SimpleNamespace(degree="G2", movements=SimpleNamespace(all=lambda: rows))
        self.assertEqual(classify(process)["outcome"], "granted")
        self.assertEqual(classify(process)["selected_evidence"][0]["movement_id"], 20)
        rows[0].occurred_at = None
        self.assertEqual(classify(process)["outcome"], "denied")
        rows[1].occurred_at = None
        self.assertEqual(classify(process)["outcome"], "unknown")

    def test_binary_rates_exclusions_and_evidence(self):
        run = ExtractionRun.objects.create(scope=SCOPE, status="sample")
        cases = [
            ("G2", [237, 237]),
            ("TR", [239]),
            ("G2", [238]),
            ("G2", [237, 239]),
            ("G2", [235]),
            ("G1", [237]),
            ("G2", [220]),
            ("G2", [240]),
        ]
        for index, (degree, codes) in enumerate(cases):
            record = hit(str(index), degree)
            record["_source"]["movimentos"] = [
                {"codigo": code, "nome": "Synthetic", "dataHora": f"2024-01-{day + 1:02}T00:00:00Z"}
                for day, code in enumerate(codes)
            ]
            load_record(normalize(record, SCOPE), run)
        metrics = self.client.get("/api/statistics/").json()["metrics"]
        self.assertEqual(metrics["binary_denominator"], 3)
        self.assertEqual(metrics["grant_rate"], 1 / 3)
        self.assertEqual(metrics["denial_rate"], 2 / 3)
        self.assertEqual(sum(metrics["excluded"].values()), 5)
        self.assertEqual(metrics["excluded"]["ambiguous"], 0)
        distribution = self.client.get("/api/distribution/?outcome=granted").json()
        self.assertEqual(distribution["denominator"], 3)
        self.assertEqual(distribution["series"], [{"outcome": "granted", "count": 1, "rate": 1 / 3}])
        self.assertEqual(self.client.get("/api/statistics/?outcome=denied").json()["metrics"], metrics)
        row = self.client.get("/api/processes/").json()["results"][0]
        self.assertEqual(row["outcome"], "granted")
        self.assertEqual(len(row["evidence"]), 2)
        self.assertEqual(row["rule_version"], "tpu-document-latest-v2")
