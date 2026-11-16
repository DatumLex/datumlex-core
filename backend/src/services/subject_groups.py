"""Display aliases only: preserve CNJ codes and never merge stored subjects."""
import re
import unicodedata

from django.db.models import Case, Count, F, IntegerField, Value, When
from src.db.models import DimSubject, FactProcessSubject


def name_key(name):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', name or '')).strip().casefold()


def matching_codes(code):
    subjects = list(DimSubject.objects.values('code', 'name'))
    chosen = next((item for item in subjects if item['code'] == code), None)
    key = name_key(chosen['name']) if chosen else ''
    return [item['code'] for item in subjects if name_key(item['name']) == key] if key else [code]


def grouped_options(subjects, courts):
    groups = {}
    for subject in subjects:
        # Unknown labels include the actual code, so unrelated unknowns stay separate.
        key = name_key(subject['name'])
        if key not in groups:
            groups[key] = {'code': subject['code'], 'name': subject['name'], 'codes': []}
        groups[key]['codes'].append(subject['code'])
    aliases = [When(subject__code__in=item['codes'], then=Value(item['code']))
               for item in groups.values() if len(item['codes']) > 1]
    counts = dict(FactProcessSubject.objects.filter(process__court__in=courts)
                  .annotate(group_code=Case(*aliases, default=F('subject__code'), output_field=IntegerField()))
                  .values('group_code').annotate(total=Count('process_id', distinct=True))
                  .values_list('group_code', 'total'))
    return [{**item, 'record_count': counts.get(item['code'], 0)} for item in groups.values()]
