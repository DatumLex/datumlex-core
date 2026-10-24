"""Import a #109 result without changing previous extractions."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from src.nlp.adapters import read_source
from src.services.nlp_evidence import persist_result


class Command(BaseCommand):
    help = 'Persist a versioned #109 output after verifying the source artifact.'

    def add_arguments(self, parser):
        parser.add_argument('result', type=Path)
        parser.add_argument('--root', type=Path, required=True)
        parser.add_argument('--request-key', required=True)
        parser.add_argument('--previous-id')
        parser.add_argument('--reason', default='')

    def handle(self, **options):
        try:
            result = json.loads(options['result'].read_text(encoding='utf-8'))
            text = None
            if result['status'] in ('completed', 'partial'):
                text = read_source(result['source'], options['root'])
            run = persist_result(result, text, request_key=options['request_key'],
                                 previous_id=options['previous_id'], reason=options['reason'])
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(str(run.pk))
