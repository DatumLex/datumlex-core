"""The overview must not wait for the optional full-text precedent analysis."""
from unittest.mock import patch

from django.test import TestCase

from tests.access_helpers import authorize_data


class OverviewPerformanceTests(TestCase):
    def setUp(self):
        authorize_data(self.client)

    @patch('src.routes.statistics.summarize_usage')
    def test_fast_statistics_never_runs_the_text_scan(self, summarize):
        response = self.client.get('/api/statistics/', {'include_precedent_usage': 'false'})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['precedent_usage'])
        self.assertEqual(response.json()['status'], 'empty')
        summarize.assert_not_called()

    @patch('src.routes.statistics.summarize_usage', return_value={'denominator': 0})
    def test_existing_clients_keep_the_default_response(self, summarize):
        response = self.client.get('/api/statistics/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['precedent_usage'], {'denominator': 0})
        summarize.assert_called_once()

    def test_invalid_or_repeated_switch_is_rejected(self):
        for query in ('include_precedent_usage=maybe', 'include_precedent_usage=false&include_precedent_usage=true'):
            self.assertEqual(self.client.get('/api/statistics/?'+query).status_code, 400)
