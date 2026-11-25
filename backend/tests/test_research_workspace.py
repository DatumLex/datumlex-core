import io
import json
from datetime import date
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from zipfile import ZipFile

from pypdf import PdfReader

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from src.accounts.models import Court
from src.db.models import ExtractionRun, LegalCorpusItem, LegalCorpusTopicMatch, LegalReference
from src.db.sampling_models import CivilSampleMember, CivilSamplingCohort
from src.etl.loader import load_record
from src.etl.transformer import normalize
from tests.test_pipeline import SCOPE, hit


@override_settings(RESEARCH_GEMINI_ENABLED=False)
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
                review_status="approved", provenance={"permissions": {"display": "allowed", "text": "allowed", "gemini": "allowed"}},
            )
            LegalCorpusTopicMatch.objects.create(item=item, topic=topic)
            cls.refs[key] = f"F{item.pk}"

    def setUp(self):
        self.client.force_login(self.user)
        self.query = "?court=TJDFT&start=2022-01-01&end=2025-01-01&topics=negativacao"

    def ask(self, question, previous=None, query=None, use_gemini=False):
        return self.client.post(
            "/api/research/chat/" + (query or self.query),
            {"question": question, "previous": previous or [], "use_gemini": use_gemini},
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

    def test_precedent_lookup_outside_datajud_dates_keeps_publication_gate(self):
        item = LegalCorpusItem.objects.create(
            origin_key="synthetic-sumula", title="Súmula 37 sintética", category="precedent",
            court="TJDFT", source_name="Tribunal de teste", content_kind="enunciado_sumular",
            source_url="https://example.org/sumula", date=date(1992, 3, 12),
            excerpt="Trecho sintético retido", review_status="approved",
            provenance={"permissions": {"display": "allowed"}, "metadata": {
                "id": "TEST:SUMULA:37", "topics": ["negativacao"], "judging_body": "Colegiado de teste",
                "verified_on": "2026-11-22", "authority": {"official_status": "consta_na_base_oficial"},
                "tpu": {"state": "pending", "codes": [10433]},
            }},
        )
        item.topic_matches.create(topic="negativacao")
        url = "/api/research/sources/" + self.query + "&category=precedent&q=Súmula 37"
        self.assertEqual(self.client.get(url).json()["total"], 0)
        expanded = url + "&all_dates=true"
        found = self.client.get(expanded).json()["items"]
        self.assertEqual([row["id"] for row in found], [f"F{item.pk}"])
        self.assertEqual(found[0]["judging_body"], "Colegiado de teste")
        self.assertEqual(found[0]["verified_on"], "2026-11-22")
        self.assertEqual(found[0]["official_tpu"], [])
        self.assertEqual(found[0]["excerpt"], "")
        self.assertEqual(self.client.get(f"/api/corpus/{item.pk}/").json()["excerpt"], "")
        self.assertEqual(self.client.get(expanded.replace("Súmula 37", "TEST:SUMULA:37")).json()["total"], 1)
        self.assertEqual(self.client.get(expanded.replace("negativacao", "saude")).json()["total"], 0)
        self.assertEqual(self.client.get(expanded.replace("category=precedent", "category=doctrine")).status_code, 400)
        item.review_status = "pending"
        item.save(update_fields=["review_status"])
        self.assertEqual(self.client.get(expanded).json()["total"], 0)

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
        self.assertEqual(denied["merit_baseline"], data["merit_baseline"])
        self.assertEqual(denied["merit_baseline"]["binary_denominator"], 1)
        self.assertIn("excluded", denied["merit_baseline"])
        self.assertEqual(self.ask("Qual a taxa no STJ?", query=self.query).status_code, 400)
        answer = self.ask("Qual a taxa no STJ?", query=combined).json()
        self.assertIn("0 registros", answer["paragraphs"][0]["text"])
        self.assertIn("(STJ)", answer["paragraphs"][0]["text"])

    def test_editorial_topics_and_exact_case_are_independent(self):
        run = ExtractionRun.objects.create(scope=SCOPE)
        source = hit()
        load_record(normalize(source, SCOPE), run)
        query = self.query + "&subject=10431,10433"
        data = self.client.get("/api/research/" + query).json()
        alternate = self.client.get("/api/research/" + query.replace("negativacao", "saude")).json()
        self.assertEqual(data["scope"]["selected_subject_codes"], [10431, 10433])
        self.assertIn(10440, data["scope"]["subject_codes"])
        self.assertEqual(data["metrics"], alternate["metrics"])
        self.assertNotEqual(data["counts"], alternate["counts"])
        self.assertEqual(data["metrics"]["process_records"], 1)
        match = self.client.get("/api/research/processes/" + query + "&cnj=0000000-00.2023.8.07.0001")
        self.assertEqual(match.json()["total"], 1)
        no_match = self.client.get("/api/research/" + query + "&cnj=00000000020238070002").json()
        self.assertEqual(no_match["metrics"]["process_records"], 0)
        self.assertEqual(no_match["counts"], data["counts"])
        self.assertEqual(self.client.get("/api/research/" + query + "&cnj=abc").status_code, 400)

    def test_record_export_matches_search_and_excludes_other_records(self):
        run = ExtractionRun.objects.create(scope=SCOPE)
        first = hit()
        second = hit("other")
        second["_source"]["numeroProcesso"] = "00000000020238070002"
        for source in (first, second):
            load_record(normalize(source, SCOPE), run)
        query = self.query + "&cnj=00000000020238070001"
        response = self.client.get("/api/research/export/" + query + "&format=xlsx&content=records")
        self.assertEqual(response.status_code, 200)
        with ZipFile(io.BytesIO(response.content)) as sheets:
            records = sheets.read("xl/worksheets/sheet1.xml")
            self.assertEqual(records.count(b"<row "), 2)
            self.assertIn(b"00000000020238070001", records)
            self.assertNotIn(b"00000000020238070002", records)
        self.assertEqual(
            self.client.get("/api/research/export/" + query + "&format=pdf&content=records").status_code, 400,
        )

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

    @override_settings(RESEARCH_CIVIL_COHORT="coverage-test")
    def test_degree_case_detail_and_coverage_share_authorized_scope(self):
        run = ExtractionRun.objects.create(scope=SCOPE)
        load_record(normalize(hit(), SCOPE), run)
        fact = run.factprocess_set.get()
        cohort = CivilSamplingCohort.objects.create(name="coverage-test", definition={"target": 300, "start_year": 2022})
        CivilSampleMember.objects.create(cohort=cohort, fact=fact, process=fact.process_dimension,
            court="TJDFT", year=fact.time.year, filing_month=fact.time.month, subject_code=10433)
        ExtractionRun.objects.create(status="failed", scope={"origin": "civil_sampling", "cohort": cohort.name,
                                                           "court": "TJDFT", "year": 2022})
        for degree, expected in (("G2", 1), ("G1", 0)):
            params = self.query + f"&degree={degree}"
            result = self.client.get("/api/research/" + params).json()
            details = self.client.get("/api/research/processes/" + params).json()
            self.assertEqual(result["metrics"]["process_records"], expected)
            self.assertEqual(details["total"], expected)
            self.assertEqual(sum(row["count"] for row in result["history"]), expected)
            if expected:
                self.assertEqual(details["items"][0]["degree"], degree)
        coverage = self.client.get("/api/research/coverage/" + self.query).json()["coverage"]
        status = {cell["year"]: cell["state"] for cell in coverage["cells"]}
        self.assertEqual(status[2022], "failed")
        self.assertEqual(status[fact.time.year], "partial")
        self.assertEqual(status[2025], "unverified")
        self.assertEqual(self.client.get("/api/research/processes/?court=STJ").status_code, 403)

    def test_downloads(self):
        pdf = self.client.get("/api/research/export/" + self.query + "&format=pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF-"))
        excel = self.client.get("/api/research/export/" + self.query + "&format=xlsx")
        with ZipFile(io.BytesIO(excel.content)) as z:
            self.assertIsNone(z.testzip())
            self.assertIn(b"book", z.read("xl/worksheets/sheet3.xml"))
            self.assertNotIn(b"other_book", z.read("xl/worksheets/sheet3.xml"))

    def test_publication_gate_on_all_categories_and_direct_detail(self):
        for category in ("jurisprudence", "precedent", "doctrine"):
            for status, permissions in (
                ("pending", {"display": "allowed", "gemini": "allowed"}),
                ("rejected", {"display": "allowed"}),
                ("unknown", {"display": "allowed"}),
                ("approved", {}),
            ):
                item = LegalCorpusItem.objects.create(origin_key=f"{category}-{status}", category=category,
                    court="" if category == "doctrine" else "TJDFT", title=f"Hidden {category} {status}",
                    date=date(2024, 2, 1), source_url="https://example.test/hidden",
                    review_status=status, provenance={"permissions": permissions}, fingerprint="private")
                LegalCorpusTopicMatch.objects.create(item=item, topic="negativacao")
                self.assertEqual(self.client.get(f"/api/corpus/{item.pk}/").status_code, 404)
                self.assertFalse(self.ask(f"F{item.pk}").json()["sources"])
        public = LegalCorpusItem.objects.get(origin_key="dec")
        self.assertEqual(self.client.get(f"/api/corpus/{public.pk}/").json()["id"], self.refs["dec"])
        other = LegalCorpusItem.objects.get(origin_key="other")
        self.assertEqual(self.client.get(f"/api/corpus/{other.pk}/").status_code, 404)
        self.assertEqual(self.client.get("/api/research/" + self.query).json()["counts"],
                         {"jurisprudence": 1, "precedent": 1, "doctrine": 1})
        self.assertEqual(self.client.get("/api/research/sources/" + self.query).json()["total"], 3)
        self.assertEqual(self.client.get("/api/corpus/review/").status_code, 403)

    def test_review_access_is_limited_by_role_and_court(self):
        own = LegalCorpusItem.objects.get(origin_key="dec")
        other = LegalCorpusItem.objects.get(origin_key="other")
        LegalCorpusItem.objects.filter(pk__in=[own.pk, other.pk]).update(review_status="pending")
        admin = get_user_model().objects.create_user(username="legal-review", approved=True, role="Admin")
        admin.courts.add(Court.objects.get(pk="TJDFT"))
        self.client.force_login(admin)
        self.assertEqual([row["id"] for row in self.client.get("/api/corpus/review/").json()["items"]], [own.pk])
        self.assertEqual(self.client.get(f"/api/corpus/review/{own.pk}/").json()["review_status"], "pending")
        self.assertEqual(self.client.get(f"/api/corpus/review/{other.pk}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/corpus/{own.pk}/").status_code, 404)

    def test_linked_reference_revocation_hides_public_catalog_item(self):
        item = LegalCorpusItem.objects.get(origin_key="precedent")
        reference = LegalReference.objects.create(reference_type="precedent", source_institution="TJDFT",
            identifier="synthetic-precedent", source_name="Test", title=item.title, source_url=item.source_url,
            approved=True, source_metadata={"permissions": {"display": "allowed"}})
        item.provenance["reference_id"] = reference.pk
        item.save(update_fields=["provenance"])
        url = f"/api/corpus/{item.pk}/"
        self.assertEqual(self.client.get(url).status_code, 200)
        reference.approved = False
        reference.save(update_fields=["approved"])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_pending_never_enters_exports_even_if_grants_are_present(self):
        LegalCorpusItem.objects.filter(origin_key="dec").update(review_status="pending", title="Private draft title")
        export = "/api/research/export/" + self.query
        pdf = self.client.get(export + "&format=pdf")
        self.assertEqual(pdf.status_code, 200)
        pdf_text = " ".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
        self.assertNotIn("Private draft title", pdf_text)
        self.assertIn("Trecho indexado book", pdf_text)
        xlsx = self.client.get(export + "&format=xlsx")
        self.assertEqual(xlsx.status_code, 200)
        with ZipFile(io.BytesIO(xlsx.content)) as sheets:
            rows = sheets.read("xl/worksheets/sheet3.xml")
            self.assertNotIn(b"Private draft title", rows)
            self.assertIn(b"book", rows)

    @override_settings(RESEARCH_GEMINI_ENABLED=True, GEMINI_API_KEY="test")
    def test_pending_and_display_only_sources_never_reach_provider(self):
        LegalCorpusItem.objects.filter(origin_key="dec").update(review_status="pending")
        LegalCorpusItem.objects.filter(origin_key="precedent").update(provenance={"permissions": {"display": "allowed"}})
        with patch("src.services.research_ai.urlopen") as provider:
            provider.return_value = self.gemini_response({
                "answer": f"No recorte há uma fonte doutrinária autorizada ({self.refs['book']}).",
                "cited_source_ids": [self.refs["book"]],
                "limitations": "Cobertura parcial da amostra.",
            })
            answer = self.ask("Há fontes sobre negativação?", use_gemini=True).json()
            self.assertEqual(answer["mode"], "gemini")
            request = json.loads(provider.call_args.args[0].data)
            sent = json.loads(request["contents"][0]["parts"][0]["text"])
            self.assertEqual([s["id"] for s in sent["sources"]], [self.refs["book"]])
            self.assertEqual(sent["metrics"]["catalog"], {"jurisprudence": 0, "precedent": 0, "doctrine": 1})

    @override_settings(RESEARCH_GEMINI_ENABLED=True, GEMINI_API_KEY="test")
    def test_revocation_during_provider_request_suppresses_the_source(self):
        def revoke(_request, timeout):
            LegalCorpusItem.objects.filter(origin_key="book").update(review_status="rejected")
            return self.gemini_response({
                "answer": f"A fonte {self.refs['book']} trata do tema.",
                "cited_source_ids": [self.refs["book"]],
                "limitations": "Recorte parcial.",
            })

        with patch("src.services.research_ai.urlopen", side_effect=revoke):
            answer = self.ask("Quais fontes de doutrina?", use_gemini=True).json()
        self.assertEqual(answer["mode"], "local")
        self.assertIn("permissões", answer["notice"])
        self.assertNotIn(self.refs["book"], {item["id"] for item in answer["sources"]})

    @staticmethod
    def gemini_response(output, finish="STOP"):
        return io.BytesIO(json.dumps({
            "candidates": [{"finishReason": finish, "content": {"parts": [{"text": json.dumps(output)}]}}]
        }).encode())

    @override_settings(RESEARCH_GEMINI_ENABLED=True, GEMINI_API_KEY="test")
    def test_source_question_respects_gemini_fulltext_denied_and_returns_narrative(self):
        from src.services import research_ai

        LegalCorpusItem.objects.filter(origin_key="book").update(
            provenance={"permissions": {
                "display": "allowed", "text": "allowed", "gemini": "allowed",
                "gemini_metadata": "allowed", "gemini_fulltext": "denied",
            }}
        )
        data = self.client.get("/api/research/" + self.query).json()
        data["metrics"]["process_records"] = 4518
        available = research_ai.findings(data)
        self.assertIn("volume", available)
        with patch("src.services.research_ai.urlopen") as provider:
            provider.return_value = self.gemini_response({
                "answer": f"No recorte há 1 item de doutrina autorizado ({self.refs['book']}).",
                "cited_source_ids": [self.refs["book"], "F999999"],
                "limitations": "Amostra parcial.",
            })
            paragraphs = research_ai.generate(available, data["scope"], "Quais doutrinas estão disponíveis?")
        request = json.loads(provider.call_args.args[0].data)
        sent = json.loads(request["contents"][0]["parts"][0]["text"])
        self.assertEqual([s["id"] for s in sent["sources"]], [self.refs["book"]])
        self.assertEqual(sent["sources"][0]["text_scope"], "metadata_only")
        self.assertNotIn("Trecho indexado", json.dumps(request))
        self.assertIn("1 item de doutrina", paragraphs[0]["text"])
        # Out-of-scope F999999 must be discarded by server validation!
        self.assertEqual(paragraphs[0]["refs"], [self.refs["book"]])

    @override_settings(RESEARCH_GEMINI_ENABLED=True, GEMINI_API_KEY="test", RESEARCH_GEMINI_COOLDOWN_SECONDS=8)
    def test_gemini_consent_minimization_grounding_and_rate(self):
        LegalCorpusItem.objects.filter(origin_key="book").update(
            review_status="approved",
            excerpt="Trecho com CPF 000.000.000-00 e CNJ 0000001-23.2024.8.07.0001.",
            provenance={"permissions": {
                "display": "allowed", "text": "allowed", "gemini": "allowed",
                "gemini_metadata": "allowed", "gemini_fulltext": "allowed",
            }},
        )
        with patch("src.services.research_ai.urlopen") as provider:
            local = self.ask("Consulte a doutrina")
            self.assertEqual(local.json()["mode"], "local")
            provider.assert_not_called()
            provider.return_value = self.gemini_response({
                "answer": f"A doutrina disponível é {self.refs['book']}, com 1 item no recorte.",
                "cited_source_ids": [self.refs["book"]],
                "limitations": "Amostra parcial.",
            })
            result = self.ask("Meu CPF é 111.111.111-11, consulte a doutrina", use_gemini=True).json()
            self.assertEqual(result["mode"], "gemini")
            self.assertEqual([doc["id"] for doc in result["sources"]], [self.refs["book"]])
            request = provider.call_args.args[0]
            serialized = request.data.decode()
            for secret in ("111.111.111-11", "000.000.000-00", "0000001-23.2024.8.07.0001", self.refs["other"]):
                self.assertNotIn(secret, serialized)
            self.assertIn('"doctrine"', json.loads(serialized)["contents"][0]["parts"][0]["text"])
            rate_limited = self.ask("Consulte a doutrina", use_gemini=True).json()
            self.assertEqual(rate_limited["mode"], "local")
            self.assertGreater(rate_limited["retry_after"], 0)
            self.assertLessEqual(rate_limited["retry_after"], 8)
            self.assertEqual(provider.call_count, 1)

    @override_settings(RESEARCH_GEMINI_ENABLED=True, GEMINI_API_KEY="test")
    def test_gemini_fallback_for_invalid_output_or_provider_error(self):
        responses = [
            {"answer": "", "cited_source_ids": [], "limitations": ""},
            {"findings": ["catalog"]},
            {"answer": "ok", "cited_source_ids": [0], "limitations": ""},
        ]
        with patch("src.services.research_ai.claim_request"), patch("src.services.research_ai.urlopen") as provider:
            for payload in responses:
                with self.subTest(payload=payload):
                    provider.return_value = self.gemini_response(payload)
                    answer = self.ask("Consulte a doutrina", use_gemini=True).json()
                    self.assertEqual(answer["mode"], "local")
                    self.assertIn("verificável", answer["notice"])
            for error in (
                TimeoutError(), URLError("offline"),
                HTTPError("https://generativelanguage.googleapis.com", 429, "quota", {}, None),
            ):
                with self.subTest(error=error):
                    provider.side_effect = error
                    answer = self.ask("Consulte a doutrina", use_gemini=True).json()
                    self.assertEqual(answer["mode"], "local")
                    self.assertTrue(answer["notice"])

    def test_c01_category_switch_does_not_inherit_previous_doctrine_topic(self):
        # Put doctrine on dano-material and precedent on dano-moral only, with "Todos os temas" active in URL
        LegalCorpusTopicMatch.objects.filter(item__origin_key="book").update(topic="dano-material")
        LegalCorpusTopicMatch.objects.filter(item__origin_key="precedent").update(topic="dano-moral")
        turn1 = self.ask("Que doutrina aparece nesta pesquisa?", query="?court=TJDFT").json()
        self.assertIn(self.refs["book"], [s["id"] for s in turn1["sources"]])
        prev = [f"Que doutrina aparece nesta pesquisa? {self.refs['book']}"]
        turn2 = self.ask("E os precedentes?", previous=prev, query="?court=TJDFT").json()
        self.assertIn(self.refs["precedent"], [s["id"] for s in turn2["sources"]])
        self.assertEqual(turn2["inherited_context"], {})

    def test_a01_full_excerpt_returned_without_blind_1000_char_cut(self):
        long_text = "EMENTA COMPLETA: " + ("Responsabilidade civil e dano moral. " * 45)
        self.assertGreater(len(long_text), 1500)
        LegalCorpusItem.objects.filter(origin_key="dec").update(excerpt=long_text)
        item = LegalCorpusItem.objects.get(origin_key="dec")
        detail = self.client.get(f"/api/corpus/{item.pk}/").json()
        self.assertEqual(detail["excerpt"], long_text)
        self.assertFalse(detail["excerpt_truncated"])
        self.assertEqual(detail["excerpt_total_length"], len(long_text))

    @override_settings(RESEARCH_GEMINI_ENABLED=True, GEMINI_API_KEY="test")
    def test_gemini_skips_empty_and_forbidden_scopes(self):
        with patch("src.services.research_ai.urlopen") as provider:
            empty = self.ask("Síntese", query=self.query + "&sources=datajud", use_gemini=True)
            self.assertIn("dados suficientes", empty.json()["notice"])
            blocked = self.ask("Síntese", query="?court=STJ", use_gemini=True)
            self.assertEqual(blocked.status_code, 403)
            provider.assert_not_called()

    def test_approved_doctrine_and_jurisprudence_expose_allowlisted_metadata_without_leaks(self):
        doc_ref = LegalReference.objects.create(
            reference_type="doctrine",
            source_institution="Senado",
            identifier="SYNTH:RIL:61:241",
            source_name="Senado Federal",
            title="Artigo sintético sobre dano reparável",
            source_url="https://example.org/ril-61-241",
            approved=True,
            source_metadata={"permissions": {"display": "allowed"}},
        )
        doctrine = LegalCorpusItem.objects.create(
            origin_key=f"reference:{doc_ref.pk}",
            category="doctrine",
            court="",
            title="Artigo sintético sobre dano reparável",
            source_name="Senado Federal",
            source_url="https://example.org/ril-61-241",
            content_kind="artigo",
            date=None,
            date_kind="publication_period",
            authors=["Autora Sintética"],
            excerpt="Trecho privado que não deve aparecer sem grant text.",
            fingerprint="synth-doc-1",
            review_status="approved",
            provenance={
                "reference_id": doc_ref.pk,
                "permissions": {"display": "allowed"},
                "package_sha256": "internal-package-hash",
                "metadata": {
                    "id": "SYNTH:RIL:61:241",
                    "issuer": "Senado Federal",
                    "year": 2024,
                    "source_locator": "RIL, v. 61, n. 241, p. 237–254, jan./mar. 2024",
                    "verified_on": "2026-11-22",
                    "topics": ["dano-material"],
                    "bibliography": {
                        "authors": ["Autora Sintética"],
                        "publication": "Revista de Informação Legislativa: RIL",
                        "publisher": "Senado Federal",
                        "place": "Brasília, DF",
                        "volume": 61,
                        "issue": 241,
                        "edition": None,
                        "pages": "237–254",
                        "period": "jan./mar. 2024",
                        "year": 2024,
                    },
                    "rights": {
                        "license": "CC BY-NC-SA 4.0",
                        "evidence": [
                            "https://example.org/ril.pdf",
                            "https://creativecommons.org/licenses/by-nc-sa/4.0/",
                        ],
                        "conditions": "PDF indica 4.0; ficha do fascículo na BDSF indica 3.0 Brasil.",
                    },
                    "archive_provenance": {"text_version_id": "secret-uuid", "text_sha256": "secret-sha"},
                    "nlp": {"potential": ["interno"]},
                    "notes": ["Nota interna privada"],
                    "metadata_sha256": "internal-meta-hash",
                },
            },
        )
        doctrine.topic_matches.create(topic="dano-material")

        jur_datajud = LegalCorpusItem.objects.create(
            origin_key="synth:jur:datajud",
            category="jurisprudence",
            court="TJDFT",
            title="Acórdão sintético com TPU derivada do DataJud",
            source_name="TJDFT",
            source_url="https://example.org/tjdft-1",
            content_kind="acordao",
            date=date(2024, 12, 10),
            date_kind="decision_date",
            excerpt="Texto integral retido.",
            fingerprint="synth-jur-1",
            review_status="approved",
            provenance={
                "permissions": {"display": "allowed"},
                "metadata": {
                    "id": "SYNTH:TJDFT:1",
                    "judging_body": "8ª Turma Cível",
                    "case_number": "0709571-76.2023.8.07.0001",
                    "verified_on": "2026-11-22",
                    "topics": ["transito", "dano-moral"],
                    "tpu": {"state": "verified_linked_datajud", "codes": [10435, 10439]},
                    "archive_provenance": {"text_sha256": "secret-jur-sha"},
                },
            },
        )
        jur_datajud.topic_matches.create(topic="transito")

        jur_label = LegalCorpusItem.objects.create(
            origin_key="synth:jur:label",
            category="jurisprudence",
            court="TJDFT",
            title="Acórdão sintético com referência e TPU por rótulo oficial",
            source_name="TJDFT",
            source_url="https://example.org/tjdft-2",
            content_kind="acordao",
            date=date(2023, 9, 8),
            date_kind="publication_date",
            excerpt="Outro texto retido.",
            fingerprint="synth-jur-2",
            review_status="approved",
            provenance={
                "permissions": {"display": "allowed"},
                "metadata": {
                    "id": "SYNTH:TJDFT:2",
                    "judging_body": "Turma Sintética",
                    "case_number": "0000000-00.2023.8.07.0001",
                    "reference_number": "REsp sintético 123/DF",
                    "topics": ["saude"],
                    "tpu": {"state": "verified_official_label", "codes": [10433]},
                    "rights": {"hide_case_number": True},
                },
            },
        )
        jur_label.topic_matches.create(topic="saude")

        doc_detail = self.client.get(f"/api/corpus/{doctrine.pk}/").json()
        self.assertIsNone(doc_detail["date"])
        self.assertEqual(doc_detail["publication_period"], "jan./mar. 2024")
        self.assertEqual(doc_detail["publication_year"], 2024)
        self.assertEqual(doc_detail["authors"], ["Autora Sintética"])
        self.assertEqual(doc_detail["bibliography"]["publication"], "Revista de Informação Legislativa: RIL")
        self.assertEqual(doc_detail["bibliography"]["volume"], 61)
        self.assertEqual(doc_detail["bibliography"]["issue"], 241)
        self.assertEqual(doc_detail["bibliography"]["pages"], "237–254")
        self.assertEqual(doc_detail["bibliography"]["publisher"], "Senado Federal")
        self.assertNotIn("edition", doc_detail["bibliography"])
        self.assertEqual(doc_detail["license"]["name"], "CC BY-NC-SA 4.0")
        self.assertIn("Autora Sintética", doc_detail["license"]["attribution"])
        self.assertEqual(doc_detail["license"]["url"], "https://creativecommons.org/licenses/by-nc-sa/4.0/")
        self.assertIn("divergência", doc_detail["license"]["version_note"])
        self.assertEqual(doc_detail["excerpt"], "")
        self.assertIsNone(doc_detail["tpu"])
        raw_doc_json = json.dumps(doc_detail, ensure_ascii=False)
        for internal in ("secret-uuid", "secret-sha", "internal-package-hash", "internal-meta-hash", "Nota interna", "Trecho privado"):
            self.assertNotIn(internal, raw_doc_json)

        jur1_detail = self.client.get(f"/api/corpus/{jur_datajud.pk}/").json()
        self.assertEqual(jur1_detail["judging_body"], "8ª Turma Cível")
        self.assertEqual(jur1_detail["case_number"], "0709571-76.2023.8.07.0001")
        self.assertEqual(jur1_detail["date_kind"], "decision_date")
        self.assertEqual(jur1_detail["official_tpu"], [])
        self.assertEqual(jur1_detail["tpu"]["state"], "verified_linked_datajud")
        self.assertEqual(jur1_detail["tpu"]["codes"], [10435, 10439])
        self.assertIn("DataJud", jur1_detail["tpu"]["label"])
        self.assertEqual(jur1_detail["excerpt"], "")
        self.assertNotIn("secret-jur-sha", json.dumps(jur1_detail))

        jur2_detail = self.client.get(f"/api/corpus/{jur_label.pk}/").json()
        self.assertIsNone(jur2_detail["case_number"])
        self.assertEqual(jur2_detail["reference_number"], "REsp sintético 123/DF")
        self.assertEqual(jur2_detail["date_kind"], "publication_date")
        self.assertEqual(jur2_detail["tpu"]["state"], "verified_official_label")
        self.assertEqual(jur2_detail["tpu"]["codes"], [10433])
        self.assertEqual(jur2_detail["excerpt"], "")

        # Verify /api/corpus/ (CorpusPanel) also returns enriched allowlisted metadata without leaks.
        catalog = self.client.get("/api/corpus/?court=TJDFT&start=2022-01-01&end=2025-12-31&category=doctrine").json()
        found_doc = next(row for row in catalog["items"] if row["id"] == doctrine.pk)
        self.assertEqual(found_doc["bibliography"]["volume"], 61)
        self.assertEqual(found_doc["license"]["name"], "CC BY-NC-SA 4.0")
        self.assertEqual(found_doc["excerpt"], "")
        self.assertNotIn("secret-uuid", json.dumps(found_doc))

    def test_general_topic_source_visible_only_when_approved_and_unfiltered_by_subtopic(self):
        ref = LegalReference.objects.create(
            reference_type="doctrine",
            source_institution="Senado",
            identifier="SYNTH:RIL:GENERAL",
            source_name="Senado Federal",
            title="Artigo sintético de escopo geral",
            source_url="https://example.org/ril-general",
            approved=False,
            source_metadata={"permissions": {}},
        )
        item = LegalCorpusItem.objects.create(
            origin_key=f"reference:{ref.pk}",
            category="doctrine",
            court="",
            title="Artigo sintético de escopo geral",
            source_name="Senado Federal",
            source_url="https://example.org/ril-general",
            content_kind="artigo",
            date=None,
            date_kind="publication_period",
            authors=["Autor A", "Autor B"],
            excerpt="Texto retido",
            fingerprint="synth-general",
            review_status="pending",
            provenance={
                "reference_id": ref.pk,
                "permissions": {},
                "metadata": {
                    "id": "SYNTH:RIL:GENERAL",
                    "year": 2020,
                    "topics": ["responsabilidade-civil"],
                    "bibliography": {
                        "publication": "Revista de Informação Legislativa: RIL",
                        "publisher": "Senado Federal",
                        "volume": 57,
                        "issue": 226,
                        "pages": "71–92",
                        "period": "abr./jun. 2020",
                        "year": 2020,
                    },
                    "rights": {"license": "CC BY-NC-SA 3.0 Brasil"},
                },
            },
        )
        # No LegalCorpusTopicMatch created (mirrors responsabilidade-civil outside TOPICS).
        all_topics_url = "/api/research/sources/?court=TJDFT&start=2022-01-01&end=2025-01-01&category=doctrine&q=SYNTH:RIL:GENERAL"
        self.assertEqual(self.client.get(all_topics_url).json()["total"], 0)
        self.assertEqual(self.client.get(f"/api/corpus/{item.pk}/").status_code, 404)

        # Grant display only (keeping text, nlp, gemini blocked and without auto-assigning a subtopic).
        ref.approved = True
        ref.source_metadata = {"permissions": {"display": "allowed"}}
        ref.save(update_fields=["approved", "source_metadata"])
        item.review_status = "approved"
        item.provenance["permissions"] = {"display": "allowed"}
        item.save(update_fields=["review_status", "provenance"])

        unfiltered = self.client.get(all_topics_url).json()
        self.assertEqual(unfiltered["total"], 1)
        row = unfiltered["items"][0]
        self.assertEqual(row["topics"], ["Responsabilidade civil (escopo geral)"])
        self.assertEqual(row["publication_period"], "abr./jun. 2020")
        self.assertEqual(row["publication_year"], 2020)
        self.assertEqual(row["license"]["name"], "CC BY-NC-SA 3.0 Brasil")
        self.assertIsNone(row["license"]["version_note"])
        self.assertEqual(row["excerpt"], "")

        # Filtering by a specific subtopic does NOT include it without explicit editorial assignment.
        filtered = self.client.get(all_topics_url + "&topics=dano-material").json()
        self.assertEqual(filtered["total"], 0)
        corpus_subtopic = self.client.get("/api/corpus/?court=TJDFT&category=doctrine&topic=dano-material&q=escopo geral").json()
        self.assertEqual(corpus_subtopic["counts"]["doctrine"], 0)

        # Revoking reference hides it again immediately.
        ref.approved = False
        ref.save(update_fields=["approved"])
        self.assertEqual(self.client.get(all_topics_url).json()["total"], 0)
        self.assertEqual(self.client.get(f"/api/corpus/{item.pk}/").status_code, 404)

    def test_general_scope_followup_multi_topic_dedup_stj_precedents_and_sparse_metadata(self):
        self.user.courts.add(Court.objects.get_or_create(code="STJ", defaults={"name": "STJ"})[0])

        # 1. General-scope doctrine (0 topic_matches) must not break follow-up chat (None in inferred set).
        general_doc = LegalCorpusItem.objects.create(
            origin_key="synth:general-followup",
            category="doctrine",
            court="",
            title="Doutrina sintética geral sem subtema",
            source_name="Editora Teste",
            source_url="https://example.org/general-doc",
            content_kind="artigo",
            date=None,
            date_kind="publication_period",
            authors=[],
            excerpt="Texto retido sem permissão",
            fingerprint="synth-general-followup",
            review_status="approved",
            provenance={
                "permissions": {"display": "allowed"},
                "metadata": {
                    "id": "SYNTH:GENERAL:1",
                    "topics": ["responsabilidade-civil"],
                    "rights": {
                        "license": "CC BY-NC-SA 4.0",
                        "evidence": ["javascript:alert(1)", "https://example.org/other"],
                    },
                },
            },
        )
        # Sparse metadata never fabricates date/TPU/bibliography or unsafe license URL.
        sparse_detail = self.client.get(f"/api/corpus/{general_doc.pk}/").json()
        self.assertIsNone(sparse_detail["date"])
        self.assertIsNone(sparse_detail["publication_year"])
        self.assertIsNone(sparse_detail["bibliography"])
        self.assertIsNone(sparse_detail["tpu"])
        self.assertIsNone(sparse_detail["license"]["url"])
        self.assertEqual(sparse_detail["excerpt"], "")

        # Follow-up referencing the general-scope source still retrieves authorized doctrine.
        follow_up = self.ask(
            "E a doutrina sobre isso?",
            previous=[f"O que diz F{general_doc.pk}?"],
            query="?court=TJDFT&start=2022-01-01&end=2025-01-01",
        )
        self.assertEqual(follow_up.status_code, 200)
        self.assertTrue(any(s["kind"] == "doctrine" for s in follow_up.json()["sources"]))

        # 2. Multi-topic item must never duplicate in counts, source browser, or exports.
        multi = LegalCorpusItem.objects.create(
            origin_key="synth:multi-topic",
            category="jurisprudence",
            court="TJDFT",
            title="Decisão sintética multitema",
            source_name="TJDFT",
            source_url="https://example.org/multi",
            content_kind="acordao",
            date=date(2024, 5, 1),
            date_kind="decision_date",
            excerpt="Texto retido",
            fingerprint="synth-multi",
            review_status="approved",
            provenance={"permissions": {"display": "allowed"}, "metadata": {"id": "SYNTH:MULTI:1"}},
        )
        multi.topic_matches.create(topic="dano-moral")
        multi.topic_matches.create(topic="dano-material")
        multi_query = "?court=TJDFT&start=2024-01-01&end=2024-12-31&topics=dano-moral,dano-material"
        panel = self.client.get("/api/research/" + multi_query).json()
        self.assertEqual(panel["counts"]["jurisprudence"], 1)
        listed = self.client.get("/api/research/sources/" + multi_query + "&category=jurisprudence").json()
        self.assertEqual(listed["total"], 1)
        self.assertEqual([row["id"] for row in listed["items"]], [f"F{multi.pk}"])

        # 3. Synthetic equivalents of STJ:SUMULA:37 (1992) and STJ:TEMA:1111 (2022, TPU 10441).
        for ident, title, kind, day, tpu_meta, topic in (
            (
                "STJ:SUMULA:37",
                "Súmula 37 do STJ sintética",
                "enunciado_sumular",
                date(1992, 3, 12),
                {"state": "pending", "codes": []},
                "dano-moral",
            ),
            (
                "STJ:TEMA:1111",
                "Tema 1111 do STJ sintético",
                "recurso_repetitivo",
                date(2022, 9, 28),
                {"state": "verified_official_code", "codes": [10441]},
                "transito",
            ),
        ):
            ref = LegalReference.objects.create(
                reference_type="precedent",
                source_institution="STJ",
                identifier=ident,
                source_name="STJ",
                title=title,
                source_url="https://example.org/" + ident.lower().replace(":", "-"),
                approved=True,
                source_metadata={"permissions": {"display": "allowed"}},
            )
            prec = LegalCorpusItem.objects.create(
                origin_key=f"reference:{ref.pk}",
                category="precedent",
                court="STJ",
                title=title,
                source_name="STJ",
                source_url=ref.source_url,
                content_kind=kind,
                date=day,
                date_kind="decision_date",
                excerpt="Enunciado retido sem grant text",
                fingerprint=ident,
                review_status="approved",
                provenance={
                    "reference_id": ref.pk,
                    "permissions": {"display": "allowed"},
                    "metadata": {"id": ident, "tpu": tpu_meta, "topics": [topic]},
                },
            )
            prec.topic_matches.create(topic=topic)

        stj_default = "/api/research/sources/?court=STJ&start=2010-01-01&end=2026-11-22&category=precedent"
        default_items = self.client.get(stj_default).json()["items"]
        default_ids = {row["identifier"] for row in default_items}
        self.assertIn("STJ:TEMA:1111", default_ids)
        self.assertNotIn("STJ:SUMULA:37", default_ids)
        tema = next(row for row in default_items if row["identifier"] == "STJ:TEMA:1111")
        self.assertEqual(tema["official_tpu"], [10441])
        self.assertEqual(tema["tpu"]["state"], "verified_official_code")
        self.assertEqual(tema["excerpt"], "")

        sumula_all_dates = self.client.get(stj_default + "&q=STJ:SUMULA:37&all_dates=true").json()
        self.assertEqual(sumula_all_dates["total"], 1)
        self.assertEqual(sumula_all_dates["items"][0]["official_tpu"], [])
        self.assertIsNone(sumula_all_dates["items"][0]["tpu"])
        self.assertEqual(sumula_all_dates["items"][0]["excerpt"], "")

        # Neither display-only precedent leaks text into PDF/XLSX exports.
        export_url = "/api/research/export/?court=STJ&start=2010-01-01&end=2026-11-22"
        pdf = self.client.get(export_url + "&format=pdf")
        self.assertEqual(pdf.status_code, 200)
        pdf_text = " ".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
        self.assertIn("Tema 1111 do STJ", pdf_text)
        self.assertNotIn("Enunciado retido sem grant text", pdf_text)
        self.assertNotIn("Texto retido sem permissão", pdf_text)

    def test_lexical_nlp_metadata_analysis_in_panel_and_chat(self):
        run = ExtractionRun.objects.create(scope=SCOPE)
        load_record(normalize(hit(), SCOPE), run)
        panel = self.client.get("/api/research/" + self.query).json()
        self.assertEqual(panel["nlp"]["method"], "spacy_tfidf_and_metadata_nlp")
        self.assertEqual(panel["nlp"]["engine"]["model"], "pt_core_news_sm")
        self.assertIn("spacy", panel["nlp"]["limitation"].lower())
        self.assertIn("tf-idf", panel["nlp"]["limitation"].lower())
        topic_ids = {row["id"] for row in panel["nlp"]["scope_metadata_topics"]}
        self.assertIn("dano-moral", topic_ids)

        chat = self.ask("Qual a taxa de provimento em dano moral e negativação indevida?").json()
        self.assertEqual(chat["nlp"]["method"], "spacy_tfidf_and_metadata_nlp")
        self.assertTrue(len(chat["nlp"]["query_lemmas"]) > 0)
        self.assertEqual(chat["nlp"]["intent"], "outcomes")
        q_ids = {row["id"] for row in chat["nlp"]["query_topics"]}
        self.assertIn("dano-moral", q_ids)
        self.assertIn("negativacao", q_ids)
