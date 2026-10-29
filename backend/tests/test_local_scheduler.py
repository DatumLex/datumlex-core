"""Local scheduler routing is tested without running collectors or external requests."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from scripts import scheduled_datajud_sync as scheduler


class LocalSchedulerTests(SimpleTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        logs = patch.object(scheduler, 'LOG_DIR', Path(directory.name))
        logs.start()
        self.addCleanup(logs.stop)
        logger = patch.object(scheduler, 'logger')
        logger.start()
        self.addCleanup(logger.stop)
        nlp = patch.object(scheduler, 'run_nlp_tools', return_value=0)
        nlp.start()
        self.addCleanup(nlp.stop)

    @patch.object(scheduler, 'run_source')
    @patch.object(scheduler, 'load_dotenv')
    def test_remote_database_cannot_be_used_as_local_collection_target(self, dotenv, run):
        with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://example@remote.invalid/db'}):
            self.assertEqual(scheduler.main(), 1)
        run.assert_not_called()

    @patch.object(scheduler, 'run_source', return_value=0)
    @patch.object(scheduler, 'load_dotenv')
    def test_local_collection_keeps_2016_scope_and_runs_all_sources(self, dotenv, run):
        with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://example@127.0.0.1/db'}):
            self.assertEqual(scheduler.main(), 0)
        self.assertEqual(run.call_args_list[0].args[1][:3], ['sync_datajud', '--start', '2016-01-01'])
        arguments = run.call_args_list[0].args[1]
        self.assertEqual(arguments[arguments.index('--page-size') + 1], '100')
        self.assertEqual(arguments[arguments.index('--max-pages') + 1], '1')
        self.assertEqual(arguments[-2:], ['--court', 'TJDFT'])
        self.assertEqual(run.call_args_list[1].args[1][-2:], ['--court', 'STJ'])
        pangea = [call.args[1] for call in run.call_args_list if call.args[1][0] == 'sync_pangea']
        self.assertEqual(len(pangea), 1)
        self.assertEqual(pangea[0][pangea[0].index('--query') + 1], 'responsabilidade civil')
        self.assertEqual(run.call_count, 4)

    @patch.object(scheduler, 'run_source', side_effect=[1] + [0] * 3)
    @patch.object(scheduler, 'load_dotenv')
    def test_source_failure_is_not_reported_as_success(self, dotenv, run):
        with patch.dict(os.environ, {'DATABASE_URL': ''}):
            self.assertEqual(scheduler.main(), 1)
        self.assertEqual(run.call_count, 4)

    def test_rotating_budget_reaches_all_courts_without_exceeding_two_pages(self):
        offset, seen = 0, set()
        for _ in range(46):
            courts, offset = scheduler.plan_courts(offset)
            self.assertEqual(len(courts), 2)
            self.assertEqual(len(set(courts)), 2)
            seen.update(courts)
        self.assertEqual(seen, set(scheduler.COURTS))
