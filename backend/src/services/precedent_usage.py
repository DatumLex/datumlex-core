"""Reproducible textual signals in a court's own ementa; never legal validation."""
import re
from collections import Counter
from datetime import date
from urllib.parse import urlparse

from django.conf import settings
from django.db.models import OuterRef, Subquery

from src.db.models import NlpTextVersion
from src.nlp.contracts import bytes_hash, fingerprint
from src.nlp.topics import classify

VERSION = 'ementa-explicit-stj-v1'
DISCLAIMER = ('Identificação automática de linguagem na ementa, sem aprovação dos desenvolvedores. '
              'Aplicação ou afastamento textual não comprova correção jurídica, aderência material ou divergência. '
              'O percentual usa apenas vínculos com aplicação ou afastamento explícito; não representa todos os processos.')
AUTHORITY = re.compile(
    r'\b(?P<kind>S[úu]mula|Tema)\s+(?:repetitivo\s+)?(?:n(?:[.º°o]|\s)*\s*)?'
    r'(?P<number>\d{1,5})\s*,?\s*(?:/\s*|d[oa]\s+)(?:STJ|Superior\s+Tribunal\s+de\s+Justi[çc]a)\b', re.I)
HEADING = re.compile(r'(?im)^[ \t]*(?:EMENTA)[ \t]*$')
END = re.compile(r'(?im)^[ \t]*(?:AC[ÓO]RD[ÃA]O|RELAT[ÓO]RIO|VOTOS?|DECIS[ÃA]O)[ \t]*$')
# Grammar must connect the use verb directly to the identified authority.
CONNECT = r"(?:\s+(?:a|o|as|os|da|do|das|dos|de|ao|aos|enunciado|enunciados|teor|na|no|caso|concreto|presente|hip[óo]tese))*\s*"
NEGATIVE_BEFORE = re.compile(
    r"(?:n[ãa]o\s+(?:(?:se|[ée])\s+)?(?:aplica(?:m)?(?:-se)?|incide(?:m)?|aplic[áa]vel)|"
    r"n[ãa]o\s+incid[êe]ncia|inaplicabilidade|afastamento|afasta-se)" + CONNECT + r"$", re.I)
NEGATIVE_AFTER = re.compile(
    r"^[\s.,:;-]*(?:(?:[ée]|[ée]\s+considerad[oa])\s+)?(?:inaplic[áa]vel|inaplicabilidade|"
    r"n[ãa]o\s+(?:se\s+)?(?:aplica(?:-se)?|incide)|afastad[oa])\b", re.I)
POSITIVE_BEFORE = re.compile(
    r"(?:aplica(?:m)?-se|aplicabilidade|incide(?:m)?|incid[êe]ncia|aplica[çc][ãa]o|observ[âa]ncia)"
    + CONNECT + r"$", re.I)
POSITIVE_AFTER = re.compile(
    r"^[\s.,:;-]*(?:[ée]\s+)?(?:aplic[áa]vel|incide|aplica-se|incid[êe]ncia|aplica[çc][ãa]o)\b(?=\s*[.,;:!?]|\s*$|\s+ao\s+caso\b)", re.I)
UNSAFE = re.compile(r'\b(?:alega|sustenta|requer|defende|pretende|argumenta|invoca|recorrente|apelante|'
                    r'agravante|embargante|poderia|poder[áa]|deveria|relator|ministro|DJe|'
                    r'pedido|pretens[ãa]o|pleiteia|rejeitad[oa]|indeferid[oa]|mas|por[ée]m|contudo)\b|'
                    r'julgado\s+em|se\s+houver|n[ãa]o\s+(?:h[áa]|se\s+afasta|[ée]\s+inaplic)', re.I)


def official_source(url):
    try:
        value = urlparse(url)
        host = (value.hostname or '').lower()
        return bool(value.scheme == 'https' and not value.username and not value.password
                    and host.endswith('.jus.br'))
    except (ValueError, TypeError):
        return False


def ementa_range(text, source):
    if source.get('content_kind') == 'ementa' or source.get('text_field') == 'ementa':
        return 0, len(text)
    start = HEADING.search(text)
    if not start:
        return None
    end = END.search(text, start.end())
    # A full text without an end marker cannot safely be attributed to the ementa.
    return (start.end(), end.start()) if end else None


def extract(text, source):
    bounds = ementa_range(text, source)
    if bounds is None:
        return None
    start, end = bounds
    results = []
    for citation in AUTHORITY.finditer(text, start, end):
        # Keep exact original offsets. Stop at paragraph boundaries and cap local context.
        left = text.rfind('\n\n', start, citation.start())
        left = max(start, left + 2 if left >= 0 else start, citation.start() - 180)
        right = text.find('\n\n', citation.end(), end)
        right = min(end, right if right >= 0 else end, citation.end() + 180)
        fragment = text[left:right]
        others = list(AUTHORITY.finditer(fragment))
        status, reason = 'mentioned', 'citation_only'
        unsafe = (UNSAFE.search(fragment) or any(c in fragment for c in '\"“”«»')
                  or len(others) != 1)
        before, after = text[left:citation.start()], text[citation.end():right]
        negative = NEGATIVE_BEFORE.search(before) or NEGATIVE_AFTER.search(after)
        positive = POSITIVE_BEFORE.search(before) or POSITIVE_AFTER.search(after)
        if positive and not negative and re.search(
                r'\b(?:n[ãa]o|sem|afast\w*|inaplic\w*|distin\w*|descabimento|impossibilidade|vedad[oa])\b', fragment, re.I):
            unsafe = True
        if unsafe:
            status, reason = 'ambiguous', 'voice_quotation_or_multiple_authorities'
        elif negative:
            status, reason = 'not_applied', 'explicit_negative_language'
        elif positive:
            status, reason = 'applied', 'explicit_application_language'
        identifier = 'STJ:' + ('SUMULA' if citation.group('kind').lower().startswith('s') else 'TEMA')
        identifier += ':' + str(int(citation.group('number')))
        results.append(dict(authority_id=identifier, authority_literal=citation.group(),
                            status=status, reason=reason, start=left, end=right, excerpt=fragment,
                            citation_start=citation.start(), citation_end=citation.end(),
                            line=text.count('\n', 0, left) + 1))
    return results


def summarize(scope, *, page=1, page_size=20):
    coverage = Counter()
    records = []
    catalog = getattr(settings, 'NLP_DASHBOARD_CATALOG', {})
    latest = NlpTextVersion.objects.filter(document_id=OuterRef('document_id')).order_by('-created_at', '-pk')
    versions = NlpTextVersion.objects.filter(
        pk=Subquery(latest.values('pk')[:1]), document__court__in=scope['court'].split(','),
    ).select_related('document').order_by('document__source_key')
    for version in versions.iterator(chunk_size=100):
        source = version.source
        if (source.get('category', 'jurisprudence') != 'jurisprudence'
                or source.get('content_kind') in ('precedent_reference', 'publication_excerpt', 'doctrine')
                or source.get('text_field') in ('tese', 'questao')
                or catalog.get(version.document.source_key, {}).get('fixture_id')
                or source.get('data_mode') == 'fixture'):
            continue
        coverage['source_documents'] += 1
        if scope.get('topic') and scope['topic'] not in classify(version.text):
            coverage['outside_topic'] += 1
            continue
        if (source.get('court') != version.document.court
                or source.get('document_id') != version.document.source_key
                or not official_source(source.get('source_url', ''))):
            coverage['unverified_source'] += 1
            continue
        if scope.get('subject') and scope['subject'] not in (source.get('subject_codes') or []):
            coverage['unconfirmed_subject'] += 1
            continue
        try:
            day = date.fromisoformat(str(source.get('decision_date') or '')[:10]).isoformat()
        except ValueError:
            coverage['undated'] += 1
            continue
        if not scope['start'] <= day <= scope['end']:
            coverage['outside_period'] += 1
            continue
        if bytes_hash(version.text.encode('utf-8')) != version.sha256:
            coverage['integrity_failed'] += 1
            continue
        findings = extract(version.text, source)
        if findings is None:
            coverage['missing_ementa'] += 1
            continue
        coverage['documents_analyzed'] += 1
        grouped = {}
        for finding in findings:
            grouped.setdefault(finding['authority_id'], []).append(finding)
        if not grouped:
            coverage['documents_without_stj_reference'] += 1
        for identifier, items in grouped.items():
            decisive = {item['status'] for item in items if item['status'] in ('applied', 'not_applied')}
            status = ('ambiguous' if len(decisive) > 1 else next(iter(decisive)) if decisive
                      else 'ambiguous' if any(item['status'] == 'ambiguous' for item in items) else 'mentioned')
            chosen = next((item for item in items if item['status'] == status), items[0])
            evidence = dict(chosen, status=status, document_id=version.document.source_key,
                            court=version.document.court, decision_date=day,
                            source_url=source['source_url'], text_version_id=str(version.pk),
                            text_sha256=version.sha256, rule_version=VERSION,
                            occurrence_count=len(items), attribution='own_ementa')
            evidence['id'] = fingerprint(evidence)
            records.append(evidence)
    counts = {key: sum(item['status'] == key for item in records)
              for key in ('applied', 'not_applied', 'mentioned', 'ambiguous')}
    denominator = counts['applied'] + counts['not_applied']
    records.sort(key=lambda item: (item['status'] not in ('applied', 'not_applied'), item['document_id'], item['authority_id']))
    offset = (page - 1) * page_size
    return dict(method=VERSION, scope=scope, period_field='decision_date',
                unit='distinct_document_authority_pair', outcome_filter_applied=False, counts=counts, denominator=denominator,
                application_rate=counts['applied'] / denominator if denominator else None,
                coverage=dict(coverage), disclaimer=DISCLAIMER,
                items=records[offset:offset + page_size],
                pagination=dict(page=page, page_size=page_size, total=len(records),
                                has_next=offset + page_size < len(records)))
