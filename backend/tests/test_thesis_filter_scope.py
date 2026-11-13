"""Synthetic regression checks for the visible thesis-list research filters."""
from datetime import date

from django.test import TestCase

from src.db.models import LegalCorpusItem, LegalCorpusTopicMatch, LegalReference
from tests.access_helpers import authorize_data


class ThesisFilterScopeTests(TestCase):
    def setUp(self):
        authorize_data(self.client)

    def reference(self, identifier, *, topic, year=None, subject=None):
        ref = LegalReference.objects.create(
            reference_type="precedent", source_institution="STJ", identifier=identifier,
            title=identifier, thesis=f"Enunciado sintético {identifier}", source_name="Synthetic",
            source_url="https://www.stj.jus.br/synthetic", subject_code=subject,
            published_at=date(year, 1, 1) if year else None,
        )
        item = LegalCorpusItem.objects.create(
            origin_key=f"reference:{ref.pk}", category="precedent", court="STJ", title=identifier,
            source_name="Synthetic", content_kind="precedent_reference", fingerprint=identifier,
            provenance={"reference_id": ref.pk},
        )
        LegalCorpusTopicMatch.objects.create(item=item, topic=topic, matched_terms=["synthetic"])
        return ref

    def query(self, **filters):
        response = self.client.get("/api/alignment/", {
            "court": "TJDFT", "start": "2016-01-01", "end": "2024-12-31", **filters,
        })
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_shared_topic_restricts_thesis_list_and_exposes_undated_coverage(self):
        self.reference("moral", topic="dano-moral")
        self.reference("material", topic="dano-material")
        result = self.query(topic="dano-moral")
        self.assertEqual([row["identifier"] for row in result["source_theses"]], ["moral"])
        self.assertEqual(len(result["thesis_groups"]), 1)
        self.assertEqual(result["metadata"]["scope"]["topic"], "dano-moral")
        self.assertEqual(result["metadata"]["source_thesis_coverage"]["undated"], 1)

    def test_cnj_subject_filters_source_theses_instead_of_only_link_counts(self):
        self.reference("matching", topic="dano-moral", subject=10433)
        self.reference("other", topic="dano-moral", subject=999)
        self.reference("unknown-subject", topic="dano-moral")
        result = self.query(subject=10433)
        self.assertEqual([row["identifier"] for row in result["source_theses"]], ["matching"])

    def test_period_keeps_old_records_and_excludes_known_outside_dates(self):
        self.reference("old-2016", topic="dano-moral", year=2016)
        self.reference("new-2024", topic="dano-moral", year=2024)
        result = self.query(end="2022-12-31")
        self.assertEqual([row["identifier"] for row in result["source_theses"]], ["old-2016"])

    def test_invalid_topics_are_rejected(self):
        for endpoint in ("alignment", "precedent-usage"):
            response = self.client.get(f"/api/{endpoint}/", {"court": "TJDFT", "topic": "unknown"})
            self.assertEqual(response.status_code, 400)
