import io
import json
from urllib.error import HTTPError
from urllib.request import Request
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from src.db.models import (
    CrossSourceLinkCandidate,
    DecisionAssessment,
    ExtractionRun,
    FactProcess,
    LegalReference,
)
from src.api.pangea_client import PangeaClient, PangeaError
from src.etl.cross_source_matching import normalize_cnj_identifier
from src.etl.loader import load_record
from src.etl.transformer import normalize
from tests.test_pipeline import SCOPE, hit


class CitationNormalizationTests(SimpleTestCase):
    def test_only_complete_cnj_numbers_are_normalized(self):
        self.assertEqual(
            normalize_cnj_identifier("0000000-00.2023.8.07.0001"),
            "00000000020238070001",
        )
        self.assertEqual(normalize_cnj_identifier("REsp 1.771.866/DF"), "")
        self.assertEqual(normalize_cnj_identifier("0000000002023807000"), "")

    @patch("src.api.pangea_client.urlopen")
    def test_pangea_oauth_error_exposes_code_without_provider_body(self, urlopen):
        urlopen.side_effect = HTTPError(
            "https://sso.example/token",
            400,
            "Bad Request",
            {},
            io.BytesIO(json.dumps({
                "error": "invalid_client",
                "error_description": "private provider diagnostic",
            }).encode()),
        )
        with self.assertRaises(PangeaError) as error:
            PangeaClient._read_json(Request("https://sso.example/token"), 1)
        self.assertIn("invalid_client", str(error.exception))
        self.assertNotIn("private provider diagnostic", str(error.exception))


class MatchSTJCitationsTests(TestCase):
    def setUp(self):
        run = ExtractionRun.objects.create(scope=SCOPE)
        load_record(normalize(hit(), SCOPE), run)
        self.local = FactProcess.objects.get(court="TJDFT")
        self.reference = LegalReference.objects.create(
            reference_type=LegalReference.PRECEDENT,
            source_institution="STJ",
            identifier="STJ-THEME-1",
            title="Synthetic sourced thesis",
            thesis="Synthetic fixture only.",
            related_decisions=[
                {"identifier": "0000000-00.2023.8.07.0001", "locator": "item 1"},
                {"identifier": "REsp 1.771.866/DF", "locator": "item 2"},
            ],
            source_name="Synthetic fixture",
            source_url="https://example.org/source",
            source_locator="fixture record",
            approval_reference="fixture",
        )

    def test_exact_identity_and_unresolved_citation_are_separate_and_idempotent(self):
        for _ in range(2):
            call_command("match_stj_citations", stdout=io.StringIO())

        matched = CrossSourceLinkCandidate.objects.get(
            reference=self.reference, local_decision=self.local,
        )
        unresolved = CrossSourceLinkCandidate.objects.get(
            reference=self.reference, local_decision__isnull=True,
        )
        self.assertEqual(matched.review_status, CrossSourceLinkCandidate.PENDING)
        self.assertEqual(matched.method, "exact_cnj_identifier")
        self.assertEqual(str(matched.confidence), "1.0000")
        self.assertEqual(unresolved.review_status, CrossSourceLinkCandidate.UNRESOLVED)
        self.assertIsNone(unresolved.confidence)
        self.assertEqual(CrossSourceLinkCandidate.objects.count(), 2)
        self.assertEqual(DecisionAssessment.objects.count(), 0)

    def test_same_identifier_across_multiple_citations_does_not_duplicate_link(self):
        self.reference.related_decisions = [
            {"identifier": "0000000-00.2023.8.07.0001"},
            {"identifier": "00000000020238070001"},
        ]
        self.reference.save(update_fields=["related_decisions"])
        call_command("match_stj_citations", stdout=io.StringIO())
        self.assertEqual(
            CrossSourceLinkCandidate.objects.filter(
                reference=self.reference, local_decision=self.local,
            ).count(),
            1,
        )
        self.assertEqual(CrossSourceLinkCandidate.objects.filter(local_decision__isnull=True).count(), 0)
