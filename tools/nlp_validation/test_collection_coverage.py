import tempfile
import unittest
from pathlib import Path

from collection_coverage import ACTIVE_COURTS, next_focused_query, report_coverage
from etl_runtime import atomic_json


class CollectionCoverageTests(unittest.TestCase):
    def test_reports_gaps_and_prioritizes_unchecked_then_oldest_query(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            atomic_json(root / 'tjdft-documents/cursor.json', {'years': {
                '2016': {'page': 2, 'last_probe': {'status': 'failed', 'page': 2}},
                '2017': {'page': 1, 'last_probe': {'status': 'empty', 'page': 0}},
            }})
            atomic_json(root / 'tjdft-documents/documents.json', {'one': {
                'decision_date': '2016-02-10', 'process_number': '123',
            }})
            pangea = root / 'pangea-raw/scopes'
            common = {'courts': list(ACTIVE_COURTS), 'page_size': 100}
            atomic_json(pangea / 'damages/manifest.json', {
                **common, 'query': 'dano moral', 'started_at': '2026-10-01',
                'status': 'completed', 'rows_returned': 0,
            })

            coverage = report_coverage(root)
            years = coverage['tjdft']['years']
            self.assertEqual(years['2016']['last_probe']['status'], 'failed')
            self.assertEqual(years['2016']['next_page'], 2)
            self.assertEqual(years['2016']['missing_publication_date'], 1)
            self.assertEqual(years['2017']['last_probe']['status'], 'empty')
            self.assertEqual(years['2018']['last_probe']['status'], 'not_checked')
            self.assertEqual(coverage['pangea']['queries']['dano moral']['status'], 'empty_page')
            self.assertEqual(next_focused_query(root), 'negativação indevida')

            atomic_json(pangea / 'credit/manifest.json', {
                **common, 'query': 'negativação indevida', 'started_at': '2026-10-02',
                'status': 'failed', 'failed_page': 1,
            })
            self.assertEqual(next_focused_query(root), 'dano moral')
