from django.db import connection
from django.test import TestCase

from src.db.models import DimProcess, DimSubject, ExtractionRun, FactProcess, FactProcessSubject
from src.etl.loader import load_record
from src.etl.transformer import normalize
from tests.test_pipeline import SCOPE, hit


class ResourceSchemaTests(TestCase):
    def setUp(self):
        self.run = ExtractionRun.objects.create(scope=SCOPE)

    def test_shared_process_and_separate_document_degrees(self):
        load_record(normalize(hit("first", "G1"), SCOPE), self.run)
        load_record(normalize(hit("appeal", "G2"), SCOPE), self.run)
        self.assertEqual(DimProcess.objects.count(), 1)
        self.assertEqual(FactProcess.objects.count(), 2)
        self.assertEqual(FactProcessSubject.objects.count(), 4)
        self.assertEqual(DimProcess.objects.get().number_process, "00000000020238070001")
        self.assertEqual(
            set(FactProcess.objects.values_list("degree_dimension__code", "result__name")),
            {("G1", "outside_degree"), ("G2", "unknown")},
        )
        row = self.client.get("/api/processes/").json()["results"][0]
        self.assertEqual(row["class"]["code"], 198)
        self.assertEqual({item["code"] for item in row["subjects"]}, {10433, 10439})
        self.assertNotEqual(DimSubject.objects.get(code=10433).pk, 10433)

    def test_result_refresh_and_missing_municipality(self):
        source = hit()
        source["_source"]["orgaoJulgador"].pop("codigoMunicipioIBGE")
        source["_source"]["movimentos"] = [
            {"codigo": 237, "nome": "Synthetic", "dataHora": "2024-01-01T00:00:00Z"}
        ]
        load_record(normalize(source, SCOPE), self.run)
        self.assertEqual(FactProcess.objects.get().result.name, "granted")
        self.assertIsNone(FactProcess.objects.get().organization.municipality_code)
        source["_source"]["movimentos"] = []
        load_record(normalize(source, SCOPE), self.run)
        self.assertEqual(FactProcess.objects.get().result.name, "unknown")
        self.assertEqual(FactProcess.objects.count(), 1)

    def test_physical_dimension_and_fact_columns(self):
        expected = {
            "dim_process": {"id_process", "number_process", "secrecy_level"},
            "dim_degree": {"id_degree", "code_degree", "name_degree"},
            "dim_result": {"id_result", "name_result"},
            "dim_class": {"id_class", "code_class", "name_class"},
            "dim_org": {"id_org", "code_org", "name_org", "ibge_code"},
            "dim_subject": {"id_subject", "code_subject", "name_subject"},
            "dim_time": {"id_time", "data", "year", "month", "day", "quarter"},
            "fact_resource": {
                "id_resource",
                "id_class",
                "id_process",
                "id_org",
                "id_degree",
                "id_time",
                "id_result",
                "quant_resource",
            },
            "fact_process_subject": {"id_resource", "id_subject"},
        }
        with connection.cursor() as cursor:
            self.assertNotIn("fact_process", connection.introspection.table_names(cursor))
            for table, columns in expected.items():
                actual = {item.name for item in connection.introspection.get_table_description(cursor, table)}
                self.assertTrue(columns <= actual, (table, columns - actual))
