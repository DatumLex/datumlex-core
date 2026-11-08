"""Offline regression checks for resumable jurisprudence collection."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import collect_tjdft_texts as collector


class CollectionRecoveryTests(unittest.TestCase):
    def test_target_caps_unique_documents(self):
        rows = [{'uuid': str(i), 'segredoJustica': False,
                 'dataJulgamento': '2016-01-01', 'inteiroTeor': 'Public decision text'}
                for i in range(25)]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with patch.object(collector, 'ROOT', directory), \
                    patch.object(collector, 'fetch_page', return_value=json.dumps({'registros': rows}).encode()), \
                    patch.object(collector.time, 'sleep'), \
                    patch.object(collector.shutil, 'disk_usage') as disk:
                disk.return_value.free = 2_000_000_000
                result = collector.collect(limit=25, directory=directory, target_total=3)
            self.assertEqual(result['full_texts_indexed'], 3)
            cursor = json.loads((directory / 'cursor.json').read_text())
            self.assertEqual(cursor['years']['2016']['page'], 0)
            self.assertEqual(cursor['next_year'], 2016)

    def test_transient_failure_retries(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.url = collector.ENDPOINT
        response.read.return_value = b'{"registros": []}'
        failure = HTTPError(collector.ENDPOINT, 502, 'Bad Gateway', {}, None)
        with patch.object(collector, 'urlopen', side_effect=[failure, response]) as fetch, \
                patch.object(collector.time, 'sleep'):
            self.assertEqual(collector.fetch_page(object()), b'{"registros": []}')
            self.assertEqual(fetch.call_count, 2)

    def test_failed_page_remains_pending_and_report_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'last-run.json').write_text('{"status":"completed"}')
            with patch.object(collector, 'fetch_page', side_effect=TimeoutError), \
                    patch.object(collector.shutil, 'disk_usage') as disk:
                disk.return_value.free = 2_000_000_000
                with self.assertRaises(TimeoutError):
                    collector.collect(limit=25, directory=directory)
            state = json.loads((directory / 'cursor.json').read_text())
            report = json.loads((directory / 'last-run.json').read_text())
            self.assertEqual(state['next_year'], 2016)
            self.assertEqual(state['years']['2016']['page'], 0)
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['failed_page'], 0)


if __name__ == '__main__':
    unittest.main()
