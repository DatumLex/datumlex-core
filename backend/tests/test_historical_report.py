import io
from datetime import date
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from src.db.models import ExtractionRun
from src.etl.loader import load_record
from src.etl.transformer import normalize
from src.services.analytical_context import resolve
from tests.access_helpers import authorize_data
from tests.test_pipeline import SCOPE, hit


class HistoricalReportTests(TestCase):
    def setUp(self):
        authorize_data(self.client)
        self.scope = {**SCOPE, "start": "2016-01-01"}
        self.record = hit("historical-2016")
        self.record["_source"]["dataAjuizamento"] = "2016-01-01T00:00:00Z"
        self.record["_source"]["movimentos"] = []
        run = ExtractionRun.objects.create(scope=self.scope, status="sample")
        load_record(normalize(self.record, self.scope), run)

    def test_earliest_year_in_api_and_nlp_context(self):
        response = self.client.get("/api/statistics/?start=2016-01-01&end=2016-12-31")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["metrics"]["process_records"], 1)
        self.assertEqual(self.client.get("/api/statistics/?start=2015-12-31").status_code, 400)
        actor = response.wsgi_request.user
        self.assertEqual(resolve(actor, {"start": "2016-01-01"})["start"], "2016-01-01")
        with self.assertRaises(ValueError):
            resolve(actor, {"start": "2015-12-31"})

    @patch("src.api.datajud_client.DataJudClient.search")
    def test_extraction_accepts_2016_and_preserves_scope_on_resume(self, search):
        self.record["sort"] = [1, "historical-2016"]
        search.side_effect = [{"hits": [self.record], "total": {"value": 1, "relation": "eq"}}]
        with self.settings(DATAJUD_API_KEY="synthetic-test-key"):
            call_command(
                "extract_datajud",
                start="2016-01-01",
                end="2016-12-31",
                subjects="10433",
                max_pages=1,
                page_size=1,
                stdout=io.StringIO(),
            )
        run = ExtractionRun.objects.latest("pk")
        self.assertEqual(run.scope["start"], "2016-01-01")
        self.assertEqual(run.status, "paused")
        search.side_effect = [{"hits": [], "total": {"value": 1, "relation": "eq"}}]
        with self.settings(DATAJUD_API_KEY="synthetic-test-key"):
            call_command("extract_datajud", resume=run.pk, max_pages=1, stdout=io.StringIO())
        run.refresh_from_db()
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.scope["start"], "2016-01-01")
        with self.assertRaises(CommandError):
            call_command("extract_datajud", start="2015-12-31", stdout=io.StringIO())

    def test_pdf_filtering_permissions_and_empty_denominator(self):
        from pypdf import PdfReader

        response = self.client.get("/api/report.pdf/?start=2016-01-01&end=2016-12-31")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertTrue(response.content.startswith(b"%PDF-"))
        text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(response.content)).pages)
        self.assertIn("2016-01-01 a 2016-12-31", text)
        self.assertIn("Indisponível (sem base binária)", text)
        self.assertNotIn("historical-2016", text)
        self.assertEqual(self.client.get("/api/report.pdf/?court=STJ").status_code, 403)
        self.assertEqual(self.client.get("/api/report.pdf/?court=TJDFT,STJ").status_code, 403)
        self.assertEqual(self.client.get("/api/report.pdf/?start=2015-01-01").status_code, 400)
        self.assertEqual(
            self.client.get(f"/api/report.pdf/?end={date.today().year + 1}-01-01").status_code, 400
        )
        self.assertEqual(self.client.post("/api/report.pdf/").status_code, 405)
        empty = self.client.get("/api/report.pdf/?start=2017-01-01&end=2017-12-31")
        self.assertEqual(empty.status_code, 200)
        text = " ".join(page.extract_text() for page in PdfReader(io.BytesIO(empty.content)).pages)
        self.assertIn("Sem registros", text)
        self.client.logout()
        self.assertEqual(self.client.get("/api/report.pdf/").status_code, 401)
