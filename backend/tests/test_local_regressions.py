"""Offline regressions for history, collection recovery and reviewed imports."""
import io
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import QueryDict
from django.test import TestCase, override_settings
from django.utils import timezone

from src.accounts.models import Court
from src.db.models import ExtractionRun, LegalReference
from src.services import analytical_context, nlp_dashboard
from src.services.statistics_service import InvalidQuery, filtered_processes


class LocalRegressions(TestCase):
    @patch('src.db.management.commands.sync_datajud.call_command')
    def test_finishing_history_does_not_append_an_incremental_batch(self, extract):
        def complete(name, **kwargs):
            self.assertEqual(name, 'extract_datajud')
            ExtractionRun.objects.create(scope={'origin': 'datajud', 'court': kwargs['court'],
                'start': kwargs['start'], 'subject_codes': [10433]}, status='completed')
        extract.side_effect = complete
        call_command('sync_datajud', subjects='10433', max_pages=5, page_size=100, stdout=io.StringIO())
        self.assertEqual(extract.call_count, 2)

    def test_2016_supported_by_both_analytical_contracts(self):
        actor = get_user_model().objects.create_user(username='history-reviewer', approved=True)
        actor.courts.add(Court.objects.get_or_create(code='STJ', defaults={'name': 'STJ'})[0])
        selected = analytical_context.resolve(actor, {'start': '2016-01-01', 'end': '2016-12-31'})
        self.assertEqual(selected['start'], '2016-01-01')
        _, scope = filtered_processes(QueryDict('court=STJ&start=2016-01-01&end=2016-12-31'))
        self.assertEqual(scope['start'], '2016-01-01')
        with self.assertRaises(InvalidQuery):
            filtered_processes(QueryDict('start=2015-12-31'))

    @override_settings(DATAJUD_API_KEY='')
    def test_missing_key_does_not_leave_running_claim(self):
        with self.assertRaises(CommandError):
            call_command('extract_datajud', start='2016-01-01', stdout=io.StringIO())
        run = ExtractionRun.objects.latest('pk')
        self.assertEqual(run.status, 'failed')
        self.assertIsNotNone(run.finished_at)

    def test_empty_sources_keep_complete_exclusion_contract(self):
        _, _, exclusions = nlp_dashboard.collect(None, {'courts': [], 'sources': [], 'subject_codes': []})
        self.assertEqual(exclusions['evidence_not_approved'], 0)

    @patch('src.db.management.commands.refresh_datajud.call_command')
    def test_refresh_respects_subject_scope_and_start_watermark(self, extract):
        run = ExtractionRun.objects.create(
            scope={'origin': 'datajud', 'court': 'TJDFT', 'update_mode': True, 'subject_codes': [10433]},
            status='completed', finished_at=timezone.now())
        start = timezone.now() - timedelta(days=10)
        ExtractionRun.objects.filter(pk=run.pk).update(started_at=start)
        ExtractionRun.objects.create(
            scope={'origin': 'datajud', 'court': 'TJDFT', 'update_mode': True, 'subject_codes': [999]},
            status='paused')
        call_command('refresh_datajud', subjects='10433', overlap_days=0, stdout=io.StringIO())
        first = extract.call_args_list[0]
        self.assertNotIn('resume', first.kwargs)
        self.assertEqual(first.kwargs['updated_since'], start.isoformat())

    @patch('src.db.management.commands.refresh_datajud.call_command')
    def test_refresh_skips_running_scope(self, extract):
        ExtractionRun.objects.create(
            scope={'origin': 'datajud', 'court': 'TJDFT', 'update_mode': True, 'subject_codes': [10433]})
        call_command('refresh_datajud', subjects='10433', stdout=io.StringIO())
        self.assertEqual([c.kwargs.get('court') for c in extract.call_args_list], ['STJ'])

    @patch('src.db.management.commands.sync_pangea.PangeaPublicSearchClient')
    def test_identical_pangea_preserves_review_but_changed_content_invalidates_it(self, client):
        row = {'id': 'test-source-1', 'orgao': 'STJ', 'tipo': 'RR', 'nr': 1, 'tese': 'Tese de teste'}
        client.return_value.get_catalog.return_value = {}
        client.return_value.search_page.return_value = {'resultados': [row], 'total': 1}
        call_command('sync_pangea', stdout=io.StringIO())
        reference = LegalReference.objects.get(identifier='test-source-1')
        reference.approved = True
        reference.approval_reference = 'Reviewed-local-test'
        reference.published_at = date(2016, 5, 1)
        reference.subject_code = 10433
        reference.save()
        call_command('sync_pangea', stdout=io.StringIO())
        reference.refresh_from_db()
        self.assertTrue(reference.approved)
        self.assertEqual(reference.published_at, date(2016, 5, 1))
        self.assertEqual(reference.subject_code, 10433)
        row['tese'] = 'Tese alterada'
        call_command('sync_pangea', stdout=io.StringIO())
        reference.refresh_from_db()
        self.assertFalse(reference.approved)
