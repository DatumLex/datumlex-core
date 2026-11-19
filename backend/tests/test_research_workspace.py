import io
import json
from datetime import date
from unittest.mock import patch
from urllib.error import URLError
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from src.accounts.models import Court
from src.db.models import ExtractionRun, LegalCorpusItem, LegalCorpusTopicMatch
from src.etl.loader import load_record
from src.etl.transformer import normalize
from tests.test_pipeline import SCOPE, hit


@override_settings(RESEARCH_OPENAI_ENABLED=False)
class ResearchWorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="researcher", approved=True, must_change_password=False
        )
        cls.user.courts.add(Court.objects.get_or_create(code="TJDFT", defaults={"name": "TJDFT"})[0])
        cls.refs = {}
        for key, kind, court, topic, day in [
            ("dec", "jurisprudence", "TJDFT", "negativacao", date(2024, 1, 2)),
            ("precedent", "precedent", "TJDFT", "negativacao", date(2023, 4, 1)),
            ("book", "doctrine", "", "negativacao", None),
            ("other", "precedent", "STJ", "negativacao", date(2024, 1, 1)),
            ("other_book", "doctrine", "", "saude", date(2024, 1, 1)),
        ]:
            item = LegalCorpusItem.objects.create(
                origin_key=key,
                title=key,
                category=kind,
                court=court,
                source_name="Acervo de teste",
                date=day,
                excerpt="Trecho indexado " + key,
                fingerprint=key,
                source_url="https://example.org/" + key,
            )
            LegalCorpusTopicMatch.objects.create(item=item, topic=topic)
            cls.refs[key] = f"F{item.pk}"

    def setUp(self):
        self.client.force_login(self.user)
        self.query = "?court=TJDFT&start=2022-01-01&end=2025-01-01&topics=negativacao"

    def ask(self, question, previous=None, query=None):
        return self.client.post(
            "/api/research/chat/" + (query or self.query),
            {"question": question, "previous": previous or []},
            content_type="application/json",
        )

    def test_scoped_panel_and_source_browser(self):
        response = self.client.get("/api/research/" + self.query)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["counts"], {"jurisprudence": 1, "precedent": 1, "doctrine": 1})
        self.assertEqual(data["metrics"]["binary_denominator"], 0)
        self.assertEqual(data["provider"], "local")
        self.assertIn(self.refs["book"], {r for p in data["summary"] for r in p["refs"]})
        r = self.client.get("/api/research/sources/" + self.query + "&category=doctrine&q=book")
        self.assertEqual([d["id"] for d in r.json()["items"]], [self.refs["book"]])
        r = self.client.get("/api/research/" + self.query + "&undated=false&sources=doctrine")
        self.assertFalse(r.json()["sources"])
        self.assertIsNone(r.json()["usage"])

    def test_real_follow_up_and_stale_citation(self):
        r = self.ask("O que diz " + self.refs["dec"] + "?")
        self.assertEqual([s["id"] for s in r.json()["sources"]], [self.refs["dec"]])
        r = self.ask("E a doutrina sobre isso?", ["O que diz " + self.refs["dec"] + "?"], "?court=TJDFT")
        self.assertEqual([s["id"] for s in r.json()["sources"]], [self.refs["book"]])
        self.assertEqual(self.ask(self.refs["other"]).json()["sources"], [])
        r = self.ask("Há doutrina?", query=self.query + "&sources=precedent")
        self.assertEqual(r.json()["sources"], [])
        self.assertEqual(self.ask(" ", []).status_code, 400)
        self.assertEqual(self.client.get("/api/research/chat/" + self.query).status_code, 405)

    def test_combined_courts_subjects_and_selected_outcomes(self):
        self.user.courts.add(Court.objects.get_or_create(code="STJ", defaults={"name": "STJ"})[0])
        run = ExtractionRun.objects.create(scope=SCOPE)
        source = hit()
        source["_source"]["movimentos"] = [
            {"codigo": 237, "nome": "Teste", "dataHora": "2024-01-01T00:00:00Z"}
        ]
        load_record(normalize(source, SCOPE), run)
        combined = self.query.replace("court=TJDFT", "court=STJ,TJDFT") + "&subject=10433,10439"
        data = self.client.get("/api/research/" + combined + "&outcomes=granted").json()
        self.assertEqual(data["metrics"]["process_records"], 1)
        self.assertEqual(data["metrics"]["grant_rate"], 1.0)
        self.assertEqual(data["history"][0]["count"], 1)
        self.assertEqual(data["counts"]["precedent"], 2)
        denied = self.client.get("/api/research/" + combined + "&outcomes=denied").json()
        self.assertEqual(denied["metrics"]["process_records"], 0)
        self.assertEqual(denied["counts"], data["counts"])
        self.assertEqual(self.ask("Qual a taxa no STJ?", query=self.query).status_code, 400)
        answer = self.ask("Qual a taxa no STJ?", query=combined).json()
        self.assertIn("0 registros", answer["paragraphs"][0]["text"])
        self.assertIn("(STJ)", answer["paragraphs"][0]["text"])

    def test_permissions_scope_validation_and_csrf(self):
        for path in ["research", "research/sources", "research/chat", "research/export"]:
            self.assertEqual(self.client.get("/api/" + path + "/?court=TJDFT,STJ").status_code, 403)
        self.assertEqual(self.client.get("/api/research/?court=TJDFT&court=TJDFT").status_code, 400)
        self.assertEqual(self.client.get("/api/research/?sources=invalid").status_code, 400)
        self.assertEqual(self.client.get("/api/research/?subject=1,x").status_code, 400)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(
            csrf.post(
                "/api/research/chat/?court=TJDFT", {"question": "teste"}, content_type="application/json"
            ).status_code,
            403,
        )
        self.client.logout()
        self.assertEqual(self.ask("doutrina").status_code, 401)

    def test_downloads(self):
        pdf = self.client.get("/api/research/export/" + self.query + "&format=pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF-"))
        excel = self.client.get("/api/research/export/" + self.query + "&format=xlsx")
        with ZipFile(io.BytesIO(excel.content)) as z:
            self.assertIsNone(z.testzip())
            self.assertIn(b"book", z.read("xl/worksheets/sheet3.xml"))
            self.assertNotIn(b"other_book", z.read("xl/worksheets/sheet3.xml"))

    @override_settings(RESEARCH_OPENAI_ENABLED=True, OPENAI_API_KEY="test")
    def test_provider_success_and_outage(self):
        with patch("src.services.research_ai.urlopen") as provider:
            output = {"paragraphs": [{"text": "Trecho do acervo.", "refs": [self.refs["book"]]}]}
            provider.return_value.__enter__.return_value = io.StringIO(
                json.dumps(
                    {
                        "status": "completed",
                        "output": [
                            {
                                "type": "message",
                                "content": [{"type": "output_text", "text": json.dumps(output)}],
                            }
                        ],
                    }
                )
            )
            answer = self.ask("Consulte a doutrina").json()
            self.assertEqual(answer["mode"], "openai")
            self.assertEqual(answer["sources"][0]["id"], self.refs["book"])
            body = json.loads(provider.call_args.args[0].data)
            self.assertFalse(body["store"])
            self.assertNotIn("other_book", body["input"])
            output["paragraphs"][0]["refs"] = ["F999999"]
            provider.return_value.__enter__.return_value = io.StringIO(
                json.dumps(
                    {
                        "status": "completed",
                        "output": [
                            {
                                "type": "message",
                                "content": [{"type": "output_text", "text": json.dumps(output)}],
                            }
                        ],
                    }
                )
            )
            self.assertEqual(self.ask("doutrina").json()["mode"], "local")
            provider.side_effect = URLError("offline")
            answer = self.ask("doutrina").json()
            self.assertEqual(answer["mode"], "local")
            self.assertTrue(answer["notice"])
