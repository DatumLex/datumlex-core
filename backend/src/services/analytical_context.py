"""Canonical #165 context, shared by NLP readers and downstream export consumers."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.nlp.contracts import fingerprint

COURTS = ('STJ', 'TJDFT')
SOURCES = ('datajud', 'tjdft_jurisprudence', 'stj_jurisprudence', 'stj_precedent', 'bdjur_doctrine')
OUTCOMES = ('granted', 'denied', 'partial', 'not_admitted', 'partial_knowledge',
            'ambiguous', 'unknown', 'outside_appellate_degree')
SUBJECTS = (10431, 10433, 10439)


def today():
    return datetime.now(ZoneInfo('America/Sao_Paulo')).date()


def permitted(actor):
    if not actor.is_authenticated or not actor.is_active or not actor.approved or actor.must_change_password:
        raise PermissionError('inactive_account')
    return set(COURTS) if actor.support else set(actor.courts.values_list('code', flat=True)) & set(COURTS)


def authorize(actor, context):
    if not set(context['courts']) <= permitted(actor):
        raise PermissionError('court_forbidden')


def resolve(actor, supplied):
    if not isinstance(supplied, dict):
        raise ValueError('context_object_required')
    defaults = {'contract_version': 'analytical-context-v1', 'courts': sorted(permitted(actor)),
                'outcomes': sorted(OUTCOMES), 'sources': sorted(SOURCES),
                'subject_codes': list(SUBJECTS), 'start': '2023-01-01', 'end': today().isoformat()}
    if set(supplied) - set(defaults):
        raise ValueError('unknown_context_field')
    result = defaults | supplied
    if result['contract_version'] != defaults['contract_version']:
        raise ValueError('unsupported_context_version')
    for field, allowed in [('courts', COURTS), ('outcomes', OUTCOMES), ('sources', SOURCES), ('subject_codes', SUBJECTS)]:
        values = result[field]
        expected_type = int if field == 'subject_codes' else str
        if (not isinstance(values, list) or any(type(v) is not expected_type for v in values)
                or not set(values) <= set(allowed)):
            raise ValueError(f'invalid_{field}')
        result[field] = sorted(set(values))
    for field in ('start', 'end'):
        value = result[field]
        if not isinstance(value, str) or len(value) != 10 or date.fromisoformat(value).isoformat() != value:
            raise ValueError(f'invalid_{field}')
    if not '2023-01-01' <= result['start'] <= result['end'] <= today().isoformat():
        raise ValueError('invalid_period')
    authorize(actor, result)
    return result


def from_query(actor, query):
    arrays = {'court[]': 'courts', 'outcome[]': 'outcomes', 'source[]': 'sources'}
    if set(query) - set(arrays) - {'subject', 'start', 'end'}:
        raise ValueError('unknown_query_field')
    supplied = {}
    for key, field in arrays.items():
        if key in query:
            values = query.getlist(key)
            if '' in values and values != ['']:
                raise ValueError('mixed_empty_selection')
            supplied[field] = [] if values == [''] else values
    for field in ('subject', 'start', 'end'):
        if field in query:
            if len(query.getlist(field)) != 1:
                raise ValueError('repeated_scalar')
            value = query[field]
            if field == 'subject':
                if not value.isascii() or not value.isdecimal():
                    raise ValueError('invalid_subject')
                supplied['subject_codes'] = [int(value)]
            else:
                supplied[field] = value
    return resolve(actor, supplied)


def identity(context):
    return fingerprint(context)
