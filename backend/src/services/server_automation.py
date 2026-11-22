"""Durable settings and queued collection; HTTP handlers never spawn jobs."""
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from src.db.court_catalog import ACTIVE_COURTS
from src.db.models import AutomationConfiguration
from src.nlp.topics import TOPICS
from src.services.analytical_context import permitted
from src.services.period import today

ZONE = ZoneInfo('America/Sao_Paulo')
SOURCES = [
    {'id': 'datajud', 'label': 'Processos e indicadores', 'provider': 'DataJud / CNJ', 'available': True},
    {'id': 'pangea', 'label': 'Precedentes e teses', 'provider': 'Pangea / BNP', 'available': True},
    {'id': 'stj_jurisprudence', 'label': 'Jurisprudência em texto completo', 'provider': 'Dados abertos do STJ', 'available': False},
    {'id': 'doctrine', 'label': 'Doutrina', 'provider': 'Senado Federal e STJ', 'available': False},
]


def defaults():
    return {'courts': list(ACTIVE_COURTS), 'sources': ['datajud', 'pangea'],
            'topics': [key for key, _, _ in TOPICS], 'subject_codes': [10431, 10433, 10439],
            'start_year': 2016, 'end_year': today().year, 'quarter_target': 300,
            'daily_at': '19:40', 'max_pages': 10}


def validate(value):
    import re
    if not isinstance(value, dict) or set(value) != set(defaults()):
        raise ValueError('Confira os campos da configuração.')
    result = dict(value)
    for name, allowed in (('courts', ACTIVE_COURTS), ('sources', ('datajud', 'pangea')),
                          ('topics', [key for key, _, _ in TOPICS])):
        required = name != 'topics' or 'pangea' in value.get('sources', [])
        if not isinstance(value[name], list) or (required and not value[name]) or any(type(v) is not str or v not in allowed for v in value[name]):
            raise ValueError('Selecione valores válidos para ' + {'courts': 'tribunais', 'sources': 'fontes', 'topics': 'temas'}[name] + '.')
        result[name] = sorted(set(value[name]))
    codes = value['subject_codes']
    if not isinstance(codes, list) or ('datajud' in result['sources'] and not codes) or len(codes) > 50 or any(type(v) is not int or not 1 <= v <= 999999999 for v in codes):
        raise ValueError('Selecione assuntos CNJ válidos.')
    result['subject_codes'] = sorted(set(codes))
    for name, low, high in (('start_year', 2016, today().year), ('end_year', 2016, today().year),
                            ('quarter_target', 1, 10000), ('max_pages', 1, 40)):
        if type(value[name]) is not int or not low <= value[name] <= high:
            raise ValueError('Valor inválido: ' + name)
    if value['start_year'] > value['end_year']:
        raise ValueError('Confira a ordem dos anos.')
    if not isinstance(value['daily_at'], str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value['daily_at']):
        raise ValueError('Informe um horário válido.')
    return result


def current():
    row, _ = AutomationConfiguration.objects.get_or_create(pk=1, defaults={'config': validate(defaults())})
    return row


def next_due(config, at=None):
    local = (at or timezone.now()).astimezone(ZONE)
    hour, minute = map(int, config['daily_at'].split(':'))
    due = datetime.combine(local.date(), time(hour, minute), tzinfo=ZONE)
    return due if due > local else due + timedelta(days=1)


def ready(row):
    return bool(getattr(settings, 'AUTOMATION_EXECUTOR_ENABLED', False) and row.runner_seen_at
                and timezone.now() - timedelta(minutes=45) <= row.runner_seen_at <= timezone.now())


def check_actor(actor, config):
    if actor is None or actor.role != 'Master' or not set(config['courts']) <= permitted(actor):
        raise PermissionError('Selecione apenas tribunais autorizados para uma conta Master ativa.')


@transaction.atomic
def save(value, actor):
    config = validate(value)
    check_actor(actor, config)
    current()
    row = AutomationConfiguration.objects.select_for_update().get(pk=1)
    row.config, row.updated_by = config, actor
    if row.enabled:
        row.next_run_at = next_due(config)
    row.save()


@transaction.atomic
def action(name, actor):
    if name not in ('enable', 'pause', 'run_once'):
        raise ValueError('Ação inválida.')
    current()
    row = AutomationConfiguration.objects.select_for_update().get(pk=1)
    if name != 'pause':
        check_actor(actor, row.config)
        if not ready(row):
            raise ValueError('O executor do servidor ainda não está conectado. A configuração pode ser salva enquanto isso.')
        if 'datajud' in row.config['sources'] and not settings.DATAJUD_API_KEY:
            raise ValueError('A integração DataJud precisa ser configurada no servidor.')
    if name == 'enable':
        row.enabled, row.next_run_at = True, next_due(row.config)
    elif name == 'pause':
        row.enabled, row.requested, row.next_run_at = False, False, None
    else:
        if row.requested or row.last_run.get('status') == 'running':
            raise ValueError('Já existe uma coleta em andamento ou aguardando execução.')
        row.requested = True
    row.updated_by = actor
    row.save()


def status():
    row = current()
    return {'mode': 'server', 'storage': 'database', 'timezone': str(ZONE), 'config': row.config,
            'enabled': row.enabled, 'requested': row.requested, 'executor_ready': ready(row),
            'next_run_at': row.next_run_at.isoformat() if row.next_run_at else None,
            'runner_seen_at': row.runner_seen_at.isoformat() if row.runner_seen_at else None,
            'datajud_key_configured': bool(settings.DATAJUD_API_KEY),
            'topics': [{'id': key, 'label': label} for key, label, _ in TOPICS],
            'sources': SOURCES, 'last_run': row.last_run or None}
