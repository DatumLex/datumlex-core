"""Slow official responses must honor a bounded, configurable read timeout."""
import io
import json
import os
from unittest.mock import patch

from django.test import SimpleTestCase

from src.api.datajud_client import DataJudClient, DataJudError
from tests.test_pipeline import SCOPE


class DataJudTimeoutTests(SimpleTestCase):
    @patch.dict(os.environ, {}, clear=True)
    @patch('src.api.datajud_client.time.sleep')
    @patch('src.api.datajud_client.urlopen')
    def test_default_timeout_allows_a_response_slower_than_45_seconds(self, open_url, sleep):
        open_url.return_value = io.BytesIO(json.dumps({'hits': {'hits': []}}).encode())
        DataJudClient('synthetic-key').search(SCOPE)
        self.assertEqual(open_url.call_args.kwargs['timeout'], 120)

    @patch.dict(os.environ, {'DATAJUD_HTTP_TIMEOUT': '180'})
    def test_configuration_and_explicit_override(self):
        self.assertEqual(DataJudClient('synthetic-key').timeout, 180)
        self.assertEqual(DataJudClient('synthetic-key', timeout=7).timeout, 7)

    def test_invalid_configuration_is_rejected_before_network_access(self):
        for value in ('0', '-1', 'nan', 'inf', '301', 'invalid'):
            with self.subTest(value=value), patch.dict(os.environ, {'DATAJUD_HTTP_TIMEOUT': value}):
                with self.assertRaises(DataJudError):
                    DataJudClient('synthetic-key')

    @patch('src.api.datajud_client.time.sleep')
    @patch('src.api.datajud_client.urlopen')
    def test_overloaded_partial_page_is_discarded_and_retried_without_changing_cursor(self, open_url, sleep):
        partial = {'timed_out': False, '_shards': {'failed': 1, 'failures': [
            {'reason': {'type': 'es_rejected_execution_exception'}},
        ]}, 'hits': {'hits': [{'unusable_partial_record': True}]}}
        complete = {'timed_out': False, '_shards': {'failed': 0}, 'hits': {'hits': []}}
        open_url.side_effect = [io.BytesIO(json.dumps(partial).encode()), io.BytesIO(json.dumps(complete).encode())]
        result = DataJudClient('synthetic-key', attempts=2).search(SCOPE, [1, 'previous'])
        self.assertEqual(result['hits'], [])
        self.assertEqual(open_url.call_count, 2)
        self.assertEqual(open_url.call_args_list[0].args[0].data, open_url.call_args_list[1].args[0].data)
        self.assertEqual(json.loads(open_url.call_args.args[0].data)['search_after'], [1, 'previous'])
        sleep.assert_any_call(10)

    @patch('src.api.datajud_client.time.sleep')
    @patch('src.api.datajud_client.urlopen')
    def test_repeated_overload_fails_without_returning_partial_hits(self, open_url, sleep):
        payload = {'timed_out': True, 'hits': {'hits': [{'unusable_partial_record': True}]}}
        open_url.side_effect = [io.BytesIO(json.dumps(payload).encode()) for _ in range(2)]
        with self.assertRaisesRegex(DataJudError, 'incomplete page was not loaded'):
            DataJudClient('synthetic-key', attempts=2).search(SCOPE)
        self.assertEqual(open_url.call_count, 2)
