"""Unit and endpoint tests for the real spaCy + scikit-learn TF-IDF NLP engine."""

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase

from src.accounts.models import Court
from src.db.models import LegalCorpusItem
from src.nlp import engine


SAMPLE_DECISIONS = [
    {
        "id": "F1",
        "court": "TJDFT",
        "title": "Cancelamento de voo e fortuito interno",
        "category": "jurisprudence",
        "url": "https://jurisdf.tjdft.jus.br/acordaos/1",
        "text": (
            "O cancelamento de voo por falha técnica configura fortuito interno da companhia aérea "
            "e gera responsabilidade objetiva com indenização por dano moral no TJDFT."
        ),
    },
    {
        "id": "F2",
        "court": "STJ",
        "title": "Negativação indevida e Súmula 385 do STJ",
        "category": "jurisprudence",
        "url": "https://dadosabertos.web.stj.jus.br/2",
        "text": (
            "O Superior Tribunal de Justiça consolidou na Súmula 385 que a inscrição indevida em "
            "cadastro de inadimplentes não gera dano moral quando há anotação legítima preexistente."
        ),
    },
    {
        "id": "F3",
        "court": "TJSP",
        "title": "Plano de saúde e recusa de cobertura",
        "category": "jurisprudence",
        "url": "https://comunicaapi.pje.jus.br/3",
        "text": (
            "A recusa injustificada de cobertura de procedimento cirúrgico por operadora de plano de saúde "
            "viola a boa-fé contratual e enseja reparação por dano moral e material."
        ),
    },
    {
        "id": "F4",
        "court": "TJDFT",
        "title": "Atraso na entrega de imóvel e lucros cessantes",
        "category": "jurisprudence",
        "url": "https://jurisdf.tjdft.jus.br/acordaos/4",
        "text": (
            "O atraso injustificado na entrega de imóvel pela construtora gera indenização por lucros cessantes "
            "e restituição de valores pagos pelo consumidor."
        ),
    },
]


class RealNlpEngineTests(SimpleTestCase):
    def test_engine_info_reports_spacy_and_sklearn(self):
        info = engine.engine_info()
        self.assertEqual(info["library"], "spaCy + scikit-learn")
        self.assertEqual(info["model"], "pt_core_news_sm")
        self.assertIn("ner", info["components"])
        self.assertIn("TfidfVectorizer", info["components"])

    def test_analyze_text_extracts_lemmas_and_entities(self):
        result = engine.analyze_text(
            "O Superior Tribunal de Justiça aplicou a Súmula 385 sobre dano moral no TJDFT."
        )
        self.assertGreater(result["token_count"], 5)
        self.assertGreaterEqual(result["sentence_count"], 1)
        self.assertTrue(len(result["lemmas"]) >= 2)
        self.assertTrue(any(e["text"] in ("TJDFT", "Superior Tribunal de Justiça", "Súmula") for e in result["entities"]))

    def test_analyze_corpus_computes_tfidf_entities_and_cosine_similarity(self):
        result = engine.analyze_corpus(
            SAMPLE_DECISIONS,
            query="cancelamento de voo companhia aérea fortuito interno",
        )
        self.assertEqual(result["corpus_stats"]["documents_analyzed"], 4)
        self.assertGreater(result["corpus_stats"]["vocabulary_size"], 5)
        self.assertTrue(len(result["top_tfidf_terms"]) > 0)
        self.assertTrue(len(result["entities"]) > 0)
        self.assertTrue(len(result["similar_documents"]) >= 1)
        # Most similar document for flight cancellation query MUST be F1!
        self.assertEqual(result["similar_documents"][0]["id"], "F1")
        self.assertGreater(result["similar_documents"][0]["similarity"], 0.2)

    def test_analyze_corpus_empty_returns_zero_stats(self):
        result = engine.analyze_corpus([])
        self.assertEqual(result["corpus_stats"]["documents_analyzed"], 0)
        self.assertEqual(result["top_tfidf_terms"], [])
        self.assertEqual(result["similar_documents"], [])


class NlpInsightsEndpointTests(TestCase):
    def setUp(self):
        self.tjdft, _ = Court.objects.get_or_create(code="TJDFT", defaults={"name": "TJDFT"})
        self.user = get_user_model().objects.create_user(
            username="nlp-insights-tester",
            approved=True,
            must_change_password=False,
        )
        self.user.courts.add(self.tjdft)
        for sample in SAMPLE_DECISIONS[:2]:
            LegalCorpusItem.objects.create(
                origin_key=f"nlp_test_{sample['id'].lower()}",
                category=sample["category"],
                source_name="Fonte Oficial Teste",
                court="TJDFT",
                title=sample["title"],
                excerpt=sample["text"],
                fingerprint=f"fp_{sample['id'].lower()}",
                source_url=sample["url"],
                review_status="approved",
                provenance={"permissions": {"display": "allowed", "text": "allowed"}},
            )

        self.client = Client()
        self.client.force_login(self.user)

    def test_nlp_insights_endpoint_returns_real_spacy_tfidf_payload(self):
        response = self.client.get(
            "/api/v2/nlp-insights/?courts=TJDFT&q=cancelamento+de+voo+dano+moral"
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["engine"]["model"], "pt_core_news_sm")
        self.assertEqual(payload["corpus_stats"]["documents_analyzed"], 2)
        self.assertTrue(len(payload["top_tfidf_terms"]) > 0)
        self.assertTrue(len(payload["similar_documents"]) >= 1)
        self.assertEqual(payload["similar_documents"][0]["title"], "Cancelamento de voo e fortuito interno")
