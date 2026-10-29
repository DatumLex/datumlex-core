from django.core.management.base import BaseCommand

from src.accounts.models import Court
from src.db.court_catalog import COURT_NAMES, ACTIVE_COURTS


class Command(BaseCommand):
    help = 'Register official DataJud courts without granting ordinary users new permissions.'

    def handle(self, **options):
        for code in ACTIVE_COURTS:
            name = COURT_NAMES[code]
            Court.objects.get_or_create(code=code, defaults={'name': name})
        self.stdout.write(f'{len(ACTIVE_COURTS)} active courts registered; acquired coverage remains separate.')
