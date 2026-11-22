"""Bounded cron entry point, separate from Gunicorn and customer computers."""
from contextlib import contextmanager
from io import StringIO
import uuid

from django.conf import settings
from django.core.management import BaseCommand, CommandError, call_command
from django.db import connection, transaction
from django.utils import timezone
from src.db.models import AutomationConfiguration, PangeaImportRun
from src.nlp.topics import TOPICS
from src.services import server_automation as service
from src.services.automation_collection import collect_datajud


@contextmanager
def executor_lock():
    if connection.vendor != 'postgresql':
        raise CommandError('O executor de produção requer PostgreSQL para impedir rodadas simultâneas.')
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', [748120263])
        locked = cursor.fetchone()[0]
    try:
        yield locked
    finally:
        if locked:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_unlock(%s)', [748120263])


def capacity():
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_database_size(current_database())')
        if cursor.fetchone()[0] >= settings.AUTOMATION_DATABASE_BUDGET_BYTES:
            raise CommandError('Limite preventivo de armazenamento atingido.')


def pangea_start(config, term):
    previous = PangeaImportRun.objects.filter(
        scope__query=term, scope__organs=config['courts'], scope__page_size=100,
    ).order_by('-pk').first()
    if previous and previous.status != PangeaImportRun.COMPLETED:
        return previous.scope.get('next_page', 0)
    return 0


@transaction.atomic
def claim():
    service.current()
    row = AutomationConfiguration.objects.select_for_update().get(pk=1)
    now = timezone.now()
    row.runner_seen_at = now
    # Holding the advisory lock proves an interrupted predecessor no longer owns it.
    if row.last_run.get('status') == 'running':
        row.last_run = {**row.last_run, 'status': 'interrupted', 'finished_at': now.isoformat()}
    if not row.requested and not (row.enabled and row.next_run_at and row.next_run_at <= now):
        row.save(update_fields=['runner_seen_at', 'last_run'])
        return None
    try:
        service.check_actor(row.updated_by, row.config)
        config = service.validate(row.config)
    except (PermissionError, ValueError):
        row.enabled, row.requested, row.next_run_at = False, False, None
        row.last_run = {'status': 'blocked', 'reason': 'configuration_or_permission_changed', 'finished_at': now.isoformat()}
        row.save()
        return None
    row.requested = False
    row.next_run_at = service.next_due(config, now) if row.enabled else None
    row.last_run = {'id': str(uuid.uuid4()), 'status': 'running', 'started_at': now.isoformat(),
                    'config': config, 'phase': 'starting', 'results': {}}
    row.save()
    return row.last_run


def execute(report):
    config = report['config']

    def publish(**values):
        if values.get('phase') in ('datajud', 'pangea'):
            capacity()
            # Recheck the configuring account between requests, not just at startup.
            row = AutomationConfiguration.objects.select_related('updated_by').get(pk=1)
            service.check_actor(row.updated_by, config)
        report.update(values)
        AutomationConfiguration.objects.filter(pk=1).update(last_run=report, runner_seen_at=timezone.now())

    failures = []
    try:
        capacity()
        if 'datajud' in config['sources']:
            try:
                report['results']['datajud'] = collect_datajud(config, publish)
            except Exception as error:
                failures.append({'source': 'datajud', 'error_type': type(error).__name__})
        if 'pangea' in config['sources']:
            terms = {key: words[0] for key, _, words in TOPICS}
            for topic in config['topics']:
                try:
                    publish(phase='pangea', topic=topic)
                    call_command('sync_pangea', query=terms[topic], courts=','.join(config['courts']),
                                 page_size=100, max_pages=1, start_page=pangea_start(config, terms[topic]), stdout=StringIO())
                except Exception as error:
                    failures.append({'source': 'pangea', 'topic': topic, 'error_type': type(error).__name__})
        pending = any(row['missing'] for row in report['results'].get('datajud', []))
        publish(status='partial_failure' if failures else 'partial' if pending else 'completed',
                phase='finished', failures=failures, finished_at=timezone.now().isoformat())
    except Exception as error:
        publish(status='failed', phase='finished', error_type=type(error).__name__, finished_at=timezone.now().isoformat())
        raise CommandError('A coleta falhou; consulte o status no painel.') from None
    return report


class Command(BaseCommand):
    help = 'Verifica a fila e executa, no máximo, uma rodada autorizada. Use cron externo a cada 15 minutos.'

    def handle(self, *args, **options):
        if not settings.AUTOMATION_EXECUTOR_ENABLED:
            self.stdout.write('Executor desativado; nenhuma coleta iniciada.')
            return
        with executor_lock() as acquired:
            if not acquired:
                self.stdout.write('Outro executor está em execução; nenhuma rodada duplicada.')
                return
            report = claim()
            if report is None:
                self.stdout.write('Sem rodada pendente. Conexão do executor registrada.')
                return
            result = execute(report)
            self.stdout.write('Rodada encerrada: ' + result['status'])
            if result['status'] == 'partial_failure':
                raise CommandError('Uma ou mais fontes falharam; consulte o painel.')
