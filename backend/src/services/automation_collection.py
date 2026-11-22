"""Bounded DataJud collection driven by a validated server configuration."""
from datetime import date, timedelta
from io import StringIO
from django.conf import settings
from django.core.management import call_command, CommandError
from django.db.models import Count, Exists, OuterRef
from src.db.models import FactProcess, FactProcessSubject
from src.services.period import today
from src.services.subject_groups import matching_subject_codes


def periods(config):
    current = today()
    for year in range(config['start_year'], config['end_year'] + 1):
        for quarter in range(1, 5):
            start = date(year, quarter * 3 - 2, 1)
            if start > current:
                continue
            following = date(year + 1, 1, 1) if quarter == 4 else date(year, quarter * 3 + 1, 1)
            yield start, min(following - timedelta(days=1), current)


def collect_datajud(config, publish):
    if not settings.DATAJUD_API_KEY:
        raise CommandError('Configure a chave pública DataJud antes de executar esta fonte.')
    target = config['quarter_target']
    query = FactProcess.objects.filter(court__in=config['courts'])
    query = query.filter(Exists(FactProcessSubject.objects.filter(
        process_id=OuterRef('pk'), subject__code__in=matching_subject_codes(config['subject_codes']),
    )))
    windows = [(start, end, query.filter(time__date__range=(start, end)).count()) for start, end in periods(config)]
    windows.sort(key=lambda row: (row[2], row[0]))
    budget = config['max_pages']
    result = []
    for start, end, before in windows:
        current = before
        exhausted = set()
        while current < target and budget > 0 and len(exhausted) < len(config['courts']):
            counts = dict(query.filter(time__date__range=(start, end)).values('court').annotate(n=Count('pk')).values_list('court', 'n'))
            courts = sorted(config['courts'], key=lambda court: (counts.get(court, 0), court))
            for court in courts:
                if court in exhausted or budget <= 0 or current >= target:
                    continue
                publish(phase='datajud', court=court, period=f'{start.year}/T{(start.month-1)//3+1}')
                output = StringIO()
                call_command('extract_datajud', court=court, start=start.isoformat(), end=end.isoformat(),
                             subjects=','.join(map(str, config['subject_codes'])), page_size=100, max_pages=1, stdout=output)
                budget -= 1
                updated = query.filter(time__date__range=(start, end)).count()
                if updated <= current:
                    exhausted.add(court)
                current = updated
        result.append({'start': start.isoformat(), 'end': end.isoformat(), 'before': before,
                       'after': current, 'target': target, 'missing': max(0, target-current)})
    return result
