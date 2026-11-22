from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch
from unittest import skipUnless
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, Client, override_settings
from django.utils import timezone
from src.accounts.models import Court, AuditEvent
from src.db.models import AutomationConfiguration, PangeaImportRun
from src.db.court_catalog import ACTIVE_COURTS
from src.services import server_automation as service
from src.db.management.commands.run_server_automation import claim, execute, pangea_start


class ServerAutomationTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username='automation-master', role='Master', approved=True)
        for code in ACTIVE_COURTS:
            self.actor.courts.add(Court.objects.get_or_create(code=code, defaults={'name': code})[0])
        self.client.force_login(self.actor)

    def put(self, config):
        return self.client.put('/api/admin/automation/', config, content_type='application/json')

    def act(self, name):
        return self.client.post('/api/admin/automation/actions/', {'action': name}, content_type='application/json')

    def connected(self):
        row = service.current()
        row.runner_seen_at = timezone.now()
        row.save()
        return row

    def test_save_persists_in_database_without_starting_jobs(self):
        response = self.put(service.defaults())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['storage'], 'database')
        row = AutomationConfiguration.objects.get(pk=1)
        self.assertFalse(row.enabled)
        self.assertFalse(row.requested)
        self.assertIsNone(row.next_run_at)
        self.assertEqual(row.updated_by, self.actor)
        self.assertEqual(self.client.get('/api/admin/automation/').json()['config'], row.config)
        self.assertTrue(AuditEvent.objects.filter(action='automation.configured').exists())

    def test_inactive_executor_cannot_be_enabled_or_queued(self):
        self.put(service.defaults())
        for action in ('enable', 'run_once'):
            self.assertEqual(self.act(action).status_code, 400)
        self.assertFalse(service.current().requested)

    @override_settings(AUTOMATION_EXECUTOR_ENABLED=True, DATAJUD_API_KEY='test-only')
    def test_fresh_heartbeat_required_and_pause_cancels_pending_work(self):
        self.put(service.defaults())
        row = self.connected()
        self.assertEqual(self.act('enable').status_code, 200)
        self.assertEqual(self.act('run_once').status_code, 200)
        self.assertEqual(self.act('run_once').status_code, 400)
        self.assertEqual(self.act('pause').status_code, 200)
        row.refresh_from_db()
        self.assertFalse(row.enabled)
        self.assertFalse(row.requested)
        self.assertIsNone(row.next_run_at)
        row.runner_seen_at = timezone.now() - timedelta(hours=1)
        row.save()
        self.assertEqual(self.act('enable').status_code, 400)

    @override_settings(AUTOMATION_EXECUTOR_ENABLED=True, DATAJUD_API_KEY='')
    def test_missing_datajud_key_does_not_start_collection(self):
        self.put(service.defaults())
        self.connected()
        self.assertEqual(self.act('enable').status_code, 400)
        self.assertEqual(self.put({**service.defaults(), 'sources': ['pangea']}).status_code, 200)
        self.assertEqual(self.act('enable').status_code, 200)

    def test_role_scope_and_csrf_are_enforced(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.actor)
        self.assertEqual(csrf_client.put('/api/admin/automation/', service.defaults(), content_type='application/json').status_code, 403)
        self.actor.courts.clear()
        self.assertEqual(self.put(service.defaults()).status_code, 403)
        for role in ('Admin', 'Padrão'):
            self.actor.role = role
            self.actor.save()
            self.assertEqual(self.client.get('/api/admin/automation/').status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get('/api/admin/automation/').status_code, 401)

    def test_validation_disallows_commands_unsupported_sources_and_invalid_ranges(self):
        for name, value in [('daily_at', '19:00; shell'), ('courts', ['INVALID']), ('sources', ['doctrine']),
                            ('max_pages', True), ('end_year', 2015), ('subject_codes', [True]), ('quarter_target', 0)]:
            with self.subTest(name=name):
                self.assertEqual(self.put({**service.defaults(), name: value}).status_code, 400)

    def test_brasilia_schedule_is_not_runner_timezone(self):
        config = {**service.defaults(), 'daily_at': '19:40'}
        at = datetime(2026, 11, 22, 22, 39, tzinfo=dt_timezone.utc)
        due = service.next_due(config, at)
        self.assertEqual(due.astimezone(dt_timezone.utc).isoformat(), '2026-11-22T22:40:00+00:00')
        self.assertEqual(service.next_due(config, due).date().isoformat(), '2026-11-23')

    def test_claim_is_paused_by_default_and_rechecks_revoked_access(self):
        self.put(service.defaults())
        self.assertIsNone(claim())
        row = service.current()
        row.requested = True
        row.save()
        self.actor.courts.clear()
        self.assertIsNone(claim())
        row.refresh_from_db()
        self.assertFalse(row.requested)
        self.assertEqual(row.last_run['status'], 'blocked')

    def test_claim_consumes_request_once_and_reports_snapshot(self):
        self.put(service.defaults())
        row = service.current()
        row.requested = True
        row.save()
        result = claim()
        self.assertEqual(result['status'], 'running')
        self.assertEqual(result['config']['quarter_target'], 300)
        self.assertIsNone(claim())

    def test_disabled_command_never_touches_collectors(self):
        with override_settings(AUTOMATION_EXECUTOR_ENABLED=False), patch('src.db.management.commands.run_server_automation.execute') as collector:
            call_command('run_server_automation')
        collector.assert_not_called()

    def test_pangea_resumes_partial_scope_without_repeating_first_page(self):
        config = service.validate(service.defaults())
        previous = PangeaImportRun.objects.create(status='partial', scope={
            'query': 'dano moral', 'organs': config['courts'], 'page_size': 100, 'next_page': 3})
        self.assertEqual(pangea_start(config, 'dano moral'), 3)
        self.assertEqual(pangea_start(config, 'outro tema'), 0)
        previous.status = 'completed'
        previous.save()
        self.assertEqual(pangea_start(config, 'dano moral'), 0)

    def test_running_executor_does_not_start_duplicate_job(self):
        from contextlib import contextmanager
        @contextmanager
        def occupied():
            yield False
        with override_settings(AUTOMATION_EXECUTOR_ENABLED=True), patch('src.db.management.commands.run_server_automation.executor_lock', occupied), patch('src.db.management.commands.run_server_automation.claim') as acquire:
            call_command('run_server_automation')
        acquire.assert_not_called()

    @skipUnless(connection.vendor == 'postgresql', 'Advisory locks require PostgreSQL')
    @override_settings(AUTOMATION_EXECUTOR_ENABLED=True)
    def test_real_postgres_lock_prevents_another_executor(self):
        other = connection.copy(alias='automation_lock_probe')
        try:
            with other.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_lock(%s)', [748120263])
            with patch('src.db.management.commands.run_server_automation.claim') as acquire:
                call_command('run_server_automation')
            acquire.assert_not_called()
        finally:
            other.close()

    @patch('src.db.management.commands.run_server_automation.capacity')
    @patch('src.db.management.commands.run_server_automation.collect_datajud', side_effect=RuntimeError('do-not-expose-secret'))
    def test_failures_are_reported_without_exposing_credentials(self, collector, capacity):
        config = {**service.defaults(), 'sources': ['datajud']}
        service.save(config, self.actor)
        row = service.current()
        row.requested = True
        row.save()
        result = execute(claim())
        self.assertEqual(result['status'], 'partial_failure')
        self.assertNotIn('do-not-expose-secret', str(service.status()))

    @patch('src.db.management.commands.run_server_automation.capacity', side_effect=RuntimeError('storage-budget'))
    @patch('src.db.management.commands.run_server_automation.collect_datajud')
    def test_capacity_guard_stops_before_collecting(self, collector, capacity):
        service.save(service.defaults(), self.actor)
        row = service.current()
        row.requested = True
        row.save()
        from django.core.management import CommandError
        with self.assertRaises(CommandError):
            execute(claim())
        collector.assert_not_called()
        self.assertEqual(service.status()['last_run']['status'], 'failed')
