import io
from datetime import date
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from src.db.models import ExtractionRun, LegalReference, PangeaImportRun
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
        pages = PdfReader(io.BytesIO(response.content)).pages
        self.assertEqual(len(pages), 5)
        text = "\n".join(page.extract_text() for page in pages)
        for section in (
            "Panorama da pesquisa",
            "Mérito recursal",
            "Relação com o STJ",
            "Evidências da pesquisa",
            "Como ler este relatório",
        ):
            self.assertIn(section, text)
        self.assertIn("01/01/2016 a 31/12/2016", text)
        self.assertIn("Indisponível (sem base binária)", text)
        self.assertIn("Registros processuais para conferência", text)
        self.assertIn("00000000020238070001", text)
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

    def test_pangea_dates_pending_review_and_court_scope(self):
        from pypdf import PdfReader

        from src.accounts.models import Court, User
        from src.services.pangea_report import report_references

        run = PangeaImportRun.objects.create(scope={"query": "responsabilidade civil"})
        defaults = dict(
            reference_type="precedent",
            source_institution="STJ",
            thesis="Tese pública de teste <b>literal</b>",
            source_name="Pangea BNP — pesquisa pública STJ",
            source_url="https://pangeabnp.pdpj.jus.br/pesquisa",
            last_import_run=run,
            approval_reference="Pendente",
            approved=False,
        )
        LegalReference.objects.create(
            identifier="undated", title="Precedente sem data", source_updated_at="2026-01-01", **defaults
        )
        LegalReference.objects.create(
            identifier="dated",
            title="Precedente datado",
            published_at="2016-05-01",
            subject_code=10433,
            **defaults,
        )
        LegalReference.objects.create(
            identifier="outside", title="Fora do período", published_at="2010-01-01", **defaults
        )
        selected = {"court": "STJ", "start": "2016-01-01", "end": "2016-12-31", "subject": 10433}
        section = report_references(selected)
        self.assertEqual(section["dated_count"], 1)
        self.assertEqual(section["undated_count"], 1)
        self.assertEqual({row["identifier"] for row in section["items"]}, {"dated", "undated"})
        self.assertIsNone(report_references({**selected, "court": "TJDFT"}))
        user = User.objects.get(username="analyst")
        user.courts.add(Court.objects.get_or_create(code="STJ", defaults={"name": "STJ"})[0])
        response = self.client.get("/api/report.pdf/?court=STJ&start=2016-01-01&end=2016-12-31&subject=10433")
        self.assertEqual(response.status_code, 200)
        text = " ".join(page.extract_text() for page in PdfReader(io.BytesIO(response.content)).pages)
        self.assertIn("Precedente sem data", text)
        self.assertIn("pendente de aprovação jurídica", text)
        self.assertIn("período não confirmado", text)
        self.assertNotIn("Fora do período", text)

    def test_annual_report_counts_use_filtered_results(self):
        from django.http import QueryDict

        from src.services.report_context import report_context
        from src.services.statistics_service import filtered_processes

        self.record["_source"]["movimentos"] = [{"codigo": 237, "dataHora": "2016-05-01T00:00:00Z"}]
        load_record(normalize(self.record, self.scope), ExtractionRun.objects.first())
        query, scope = filtered_processes(QueryDict("court=TJDFT&start=2016-01-01&end=2016-12-31"))
        context = report_context(query, scope)
        self.assertEqual(context["annual"], [{"time__year": 2016, "documents": 1, "granted": 1, "denied": 0}])
        self.assertEqual(context["assessments"], {})
