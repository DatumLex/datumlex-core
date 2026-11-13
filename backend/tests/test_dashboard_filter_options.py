"""Regression checks for CNJ labels and the separate ten-topic corpus filter."""
from django.test import TestCase

from src.accounts.models import Court, User
from src.db.court_catalog import ACTIVE_COURTS
from src.db.models import DimSubject, ExtractionRun
from src.etl.loader import load_record
from src.etl.transformer import normalize
from src.nlp.topics import TOPICS
from tests.access_helpers import authorize_data
from tests.test_pipeline import SCOPE, hit


class DashboardFilterOptionsTests(TestCase):
    def setUp(self):
        authorize_data(self.client)
        run = ExtractionRun.objects.create(scope=SCOPE, status="sample")
        load_record(normalize(hit(), SCOPE), run)

    def test_blank_subject_names_keep_their_real_cnj_code(self):
        subjects = list(DimSubject.objects.all())
        for subject, name in zip(subjects, ["", "   "]):
            subject.name = name
            subject.save()
        response = self.client.get("/api/scope/")
        self.assertEqual(response.status_code, 200)
        options = response.json()["subjects"]
        self.assertEqual(len(options), len(subjects))
        for option in options:
            self.assertEqual(option["name"], f"Assunto CNJ {option['code']} (nome não informado)")
            self.assertGreater(option["record_count"], 0)

    def test_ten_authorized_courts_and_ten_named_topics_even_without_data(self):
        user = User.objects.get(username="analyst")
        for code in ACTIVE_COURTS:
            user.courts.add(Court.objects.get_or_create(code=code, defaults={"name": code})[0])
        response = self.client.get("/api/auth/me/")
        self.assertEqual(set(response.json()["user"]["courts"]), set(ACTIVE_COURTS))
        response = self.client.get("/api/corpus/", {"court": ",".join(ACTIVE_COURTS), "start": "2016-01-01"})
        self.assertEqual(response.status_code, 200)
        topics = response.json()["topics"]
        self.assertEqual(len(topics), 10)
        self.assertEqual({topic["id"] for topic in topics}, {key for key, _, _ in TOPICS})
        self.assertTrue(all(topic["label"].strip() for topic in topics))
        self.assertEqual(response.json()["scope"]["start"], "2016-01-01")

    def test_court_filter_does_not_grant_access_to_unapproved_courts(self):
        response = self.client.get("/api/corpus/", {"court": "TJDFT,TJSP"})
        self.assertEqual(response.status_code, 403)
