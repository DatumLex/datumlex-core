"""Real NLP processing inventory, separate from human-approved legal evidence."""
from datetime import date

from django.conf import settings

from src.db.models import NlpExtraction
from src.services import analytical_context, nlp_dashboard


def report_nlp(scope, actor=None):
    counts = dict(documents=0, processed=0, in_period=0, undated=0,
                  subject_unconfirmed=0, outside_period=0, released=0, reviewed_evidence=0)
    catalog = getattr(settings, 'NLP_DASHBOARD_CATALOG', {})
    # One latest attempt per source document; repeated processing never inflates coverage.
    runs = NlpExtraction.objects.filter(document__court__in=scope['court'].split(','))
    runs = runs.select_related('document').order_by('document_id', '-created_at', '-pk')
    seen = set()
    for run in runs.iterator(chunk_size=200):
        if run.document_id in seen:
            continue
        seen.add(run.document_id)
        source = run.original_result.get('source', {})
        mapping = catalog.get(run.document.source_key, {})
        if mapping.get('fixture_id') or run.original_result.get('data_mode') == 'fixture':
            continue
        counts['documents'] += 1
        if run.status != 'completed' or run.text_version_id is None:
            continue
        counts['processed'] += 1
        if scope['subject'] and scope['subject'] not in source.get('subject_codes', []):
            counts['subject_unconfirmed'] += 1
            continue
        value = source.get('decision_date') or source.get('publication_date')
        try:
            day = date.fromisoformat(str(value)[:10]).isoformat() if value else None
        except ValueError:
            day = None
        if day is None:
            counts['undated'] += 1
        elif scope['start'] <= day <= scope['end']:
            counts['in_period'] += 1
        else:
            counts['outside_period'] += 1
    if actor is not None:
        supplied = dict(courts=scope['court'].split(','), start=scope['start'], end=scope['end'])
        if scope['subject']:
            supplied['subject_codes'] = [scope['subject']]
        # PDF permits any TPU code; unsupported reviewed NLP taxonomy is an empty selection.
        if scope['subject'] and scope['subject'] not in analytical_context.SUBJECTS:
            supplied['subject_codes'] = []
        context = analytical_context.resolve(actor, supplied)
        documents, evidence, exclusions = nlp_dashboard.collect(actor, context)
        payload = nlp_dashboard.materialize(context, documents, evidence, exclusions)
        if payload['data_mode'] == 'live':
            counts['released'] = sum(p['denominator'] for p in payload['populations'].values())
            counts['reviewed_evidence'] = len(evidence)
    return counts


def coverage_note(counts):
    return (f"{counts['processed']} documentos processados nos tribunais selecionados; "
            f"{counts['in_period']} com data e assunto compatíveis; "
            f"{counts['undated']} sem data; {counts['subject_unconfirmed']} sem assunto confirmado; "
            f"{counts['outside_period']} fora do período. "
            f"{counts['released']} documentos liberados e {counts['reviewed_evidence']} evidências aprovadas. "
            "Processamento automático não equivale a revisão jurídica. Datas NLP são de decisão/publicação, não ajuizamento.")
