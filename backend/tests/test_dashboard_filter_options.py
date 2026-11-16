"""Regression checks for CNJ labels and the separate ten-topic corpus filter."""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
from django.test import TestCase, TransactionTestCase
from django.db import connection

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

    def test_same_named_codes_are_one_option_with_unique_record_count(self):
        self.grouped_fixture()
        response = self.client.get('/api/scope/')
        self.assertEqual(response.status_code, 200)
        groups = response.json()['subject_groups']
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['codes'], [10433, 10439])
        self.assertEqual(groups[0]['record_count'], 2)  # Not 3: one record has both codes.
        response = self.client.get('/api/statistics/', {'subject': 10433, 'include_precedent_usage': 'false'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['metrics']['process_records'], 2)

    def grouped_fixture(self):
        DimSubject.objects.filter(code=10433).update(name='Acidente de Trânsito')
        DimSubject.objects.filter(code=10439).update(name='  ACIDENTE  DE TRÂNSITO  ')
        other = deepcopy(hit('synthetic-only-alias'))
        other['_source']['assuntos'] = [{'codigo': 10439, 'nome': '  ACIDENTE  DE TRÂNSITO  '}]
        load_record(normalize(other, SCOPE), ExtractionRun.objects.first())

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


class GroupedSubjectExportTests(TransactionTestCase):
    setUp = DashboardFilterOptionsTests.setUp

    def _fixture_teardown(self):
        if connection.vendor != 'postgresql':
            return super()._fixture_teardown()
        if not connection.settings_dict['NAME'].startswith('test_'):
            raise RuntimeError('Refusing cleanup outside a test database')
        from importlib import import_module
        tables = import_module('src.db.migrations.0011_nlp_history_guards').TABLES
        with connection.cursor() as cursor:
            for table in tables:
                cursor.execute(f'ALTER TABLE {table} DISABLE TRIGGER nlp_no_truncate')
        try:
            super()._fixture_teardown()
        finally:
            with connection.cursor() as cursor:
                for table in tables:
                    cursor.execute(f'ALTER TABLE {table} ENABLE TRIGGER nlp_no_truncate')

    def test_excel_includes_all_codes_in_the_group(self):
        # A real outer transaction is needed for the export's repeatable-read snapshot.
        DashboardFilterOptionsTests.grouped_fixture(self)
        export = self.client.get('/api/report.xlsx/', {'subject': 10433})
        self.assertEqual(export.status_code, 200)
        with ZipFile(BytesIO(export.content)) as archive:
            xml = b' '.join(archive.read(name) for name in archive.namelist() if name.endswith('.xml'))
        self.assertIn(b'synthetic-only-alias', xml)
