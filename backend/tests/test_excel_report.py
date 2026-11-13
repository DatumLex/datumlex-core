from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from django.test import TestCase, SimpleTestCase
from src.db.models import ExtractionRun
from src.etl.loader import load_record
from src.etl.transformer import normalize
from src.services.excel_report import workbook
from tests.access_helpers import authorize_data
from tests.test_pipeline import SCOPE, hit

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


class ExcelTests(TestCase):
    def setUp(self):
        authorize_data(self.client)
        run = ExtractionRun.objects.create(scope=SCOPE, status="sample")
        for index in range(105):
            load_record(normalize(hit(f"export-{index}"), SCOPE), run)

    def test_all_documents_filters_and_types(self):
        response = self.client.get('/api/report.xlsx/?start=2023-01-01&end=2023-12-31&subject=10433')
        self.assertEqual(response.status_code, 200)
        self.assertIn('spreadsheetml.sheet', response['Content-Type'])
        self.assertEqual(response['Cache-Control'], 'no-store')
        with ZipFile(BytesIO(response.content)) as archive:
            for name in archive.namelist():
                ET.fromstring(archive.read(name))
            sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            rows = sheet.findall('m:sheetData/m:row', NS)
            self.assertEqual(len(rows), 106)
            self.assertEqual(rows[1][2].attrib['t'], 'inlineStr')
            self.assertEqual(rows[1][2].find('m:is/m:t', NS).text, '00000000020238070001')
            self.assertEqual(rows[1][0].attrib['t'], 'n')
        for filters in ('start=2024-01-01&end=2024-12-31', 'subject=999999'):
            empty = self.client.get('/api/report.xlsx/?' + filters)
            with ZipFile(BytesIO(empty.content)) as archive:
                sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
                self.assertEqual(len(sheet.findall('m:sheetData/m:row', NS)), 1)

    def test_permissions_validation_and_method(self):
        for court in ('STJ', 'TJDFT,STJ'):
            self.assertEqual(self.client.get('/api/report.xlsx/?court=' + court).status_code, 403)
        self.assertEqual(self.client.get('/api/report.xlsx/?start=2015-01-01').status_code, 400)
        self.assertEqual(self.client.get('/api/report.xlsx/?outcome=granted').status_code, 400)
        self.assertEqual(self.client.post('/api/report.xlsx/').status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.get('/api/report.xlsx/').status_code, 401)


class LiteralTextTests(SimpleTestCase):
    def test_formula_text_xml_escaping_and_numbers(self):
        with ZipFile(BytesIO(workbook([('Dados', [['Texto', 'Número'], ['=HYPERLINK("x") & <ação>\x00', 42]])]))) as archive:
            sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            self.assertFalse(sheet.findall('.//m:f', NS))
            self.assertEqual(sheet.find('.//m:row[@r="2"]/m:c/m:is/m:t', NS).text, '=HYPERLINK("x") & <ação>')


    def test_explicit_utf8_and_unicode_roundtrip(self):
        texts = ["Ação, órgão, instância, indenização, São Paulo", "€ £ © § — ç ã ê ü", "日本語 العربية ⚖️ 😀", "e\u0301", "  texto\tcom\nlinhas  "]
        with ZipFile(BytesIO(workbook([('Ações', [['Descrição'], *[[text] for text in texts]])]))) as archive:
            for name in archive.namelist():
                data = archive.read(name)
                self.assertTrue(data.startswith(b'<?xml version="1.0" encoding="UTF-8"'))
                data.decode('utf-8', errors='strict')
                ET.fromstring(data)
            sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            values = [row[0].find('m:is/m:t', NS).text for row in sheet.findall('m:sheetData/m:row', NS)[1:]]
            self.assertEqual(values, texts)

    def test_malformed_controls_and_surrogates(self):
        with ZipFile(BytesIO(workbook([('Dados', [['ação\x00\x0b\ud800\ufffe\uffff & <órgão>']])]))) as archive:
            sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            self.assertEqual(sheet.find('.//m:t', NS).text, 'ação & <órgão>')

    def test_large_unicode_export_and_literal_formula_prefixes(self):
        prefixes = ['=1+1', '+SUM(1,2)', '-1+2', '@SUM(A1)', '\t=1+1']
        rows = ([f'Ação {i} — órgão', prefixes[i % len(prefixes)], i] for i in range(10000))
        with ZipFile(BytesIO(workbook([('Dados', rows)]))) as archive:
            sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            exported = sheet.findall('m:sheetData/m:row', NS)
            self.assertEqual(len(exported), 10000)
            self.assertEqual(exported[-1][0].find('m:is/m:t', NS).text, 'Ação 9999 — órgão')
            self.assertFalse(sheet.findall('.//m:f', NS))
            for i, prefix in enumerate(prefixes):
                self.assertEqual(exported[i][1].find('m:is/m:t', NS).text, prefix)
