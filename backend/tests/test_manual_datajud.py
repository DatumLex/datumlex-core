"""Synthetic tests for the manual recovery's canonical normalization contract."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import sys

from django.test import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from popular_datajud_historico import normalize_backup
from src.db.models import ExtractionRun, FactProcess
from src.db.subject_catalog import DEFAULT_DATAJUD_SUBJECT_CODES
from src.etl.loader import load_record
from tests.test_pipeline import hit


class ManualDataJudRecoveryTests(TestCase):
    def row(self, court='TJDFT'):
        raw = deepcopy(hit('manual-fixture')['_source'])
        raw['tribunal'] = court
        return {
            'court':court,'source_id':('' if court=='TJDFT' else court+':')+'manual-fixture',
            'raw_payload':raw,'source_scope':{'origin':'datajud'},
        }

    def normalize(self, row):
        return normalize_backup(row,date(2016,1,1),date(2026,11,15),list(DEFAULT_DATAJUD_SUBJECT_CODES))

    def test_uses_canonical_fields_and_loader_without_duplicate_rows(self):
        record=self.normalize(self.row())
        run=ExtractionRun.objects.create(scope={'origin':'datajud_backup_recovery'})
        self.assertEqual(load_record(record,run),'created')
        self.assertEqual(load_record(record,run),'updated')
        self.assertEqual(FactProcess.objects.count(),1)
        process=FactProcess.objects.get()
        self.assertEqual(process.court,'TJDFT')
        self.assertEqual(process.raw_payload,record['raw'])
        self.assertEqual(process.payload_hash,record['payload_hash'])
        self.assertTrue(process.subjects.exists())

    def test_all_ten_courts_preserve_namespaced_identity(self):
        from src.db.court_catalog import ACTIVE_COURTS
        self.assertEqual(len(ACTIVE_COURTS),10)
        for court in ACTIVE_COURTS:
            with self.subTest(court=court):
                row=self.row(court)
                self.assertEqual(self.normalize(row)['source_id'],row['source_id'])

    def test_private_or_fixture_records_are_rejected(self):
        private=self.row();private['raw_payload']['nivelSigilo']=1
        sample=self.row();sample['source_scope']['origin']='file_sample'
        for row in (private,sample):
            with self.assertRaises(ValueError): self.normalize(row)

    def test_filing_outside_period_is_rejected(self):
        row=self.row();row['raw_payload']['dataAjuizamento']='2015-01-01T00:00:00Z'
        with self.assertRaises(ValueError): self.normalize(row)
