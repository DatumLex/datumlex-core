from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from src.db.models import ExtractionRun
from src.db.subject_catalog import DEFAULT_DATAJUD_SUBJECT_CODES_CSV
from src.db.court_catalog import ACTIVE_COURTS as COURTS


class Command(BaseCommand):
    help = "Incrementally refresh TJDFT and STJ DataJud records for the dashboard."

    def add_arguments(self, parser):
        parser.add_argument('--court', choices=COURTS, help='Optional single-court batch')
        parser.add_argument("--subjects", default=DEFAULT_DATAJUD_SUBJECT_CODES_CSV)
        parser.add_argument("--page-size", type=int, default=100)
        parser.add_argument("--max-pages", type=int, default=5)
        parser.add_argument("--overlap-days", type=int, default=3)
        parser.add_argument("--initial-lookback-days", type=int, default=30)

    def handle(self, *args, **options):
        if (options["max_pages"] < 1 or options["overlap_days"] < 0
                or options["initial_lookback_days"] < 1 or not 1 <= options["page_size"] <= 1000):
            raise CommandError("Use max-pages >= 1, overlap-days >= 0 and initial-lookback-days >= 1")
        try:
            subjects = sorted({int(code.strip()) for code in options["subjects"].split(",")})
            if not subjects or min(subjects) < 1:
                raise ValueError
        except ValueError:
            raise CommandError("Use positive subject codes") from None

        for court in ([options['court']] if options.get('court') else ("TJDFT", "STJ")):
            candidates = ExtractionRun.objects.filter(
                scope__origin="datajud",
                scope__court=court,
                scope__update_mode=True,
            ).order_by("-started_at", "-pk")
            prior = [run for run in candidates if run.scope.get("subject_codes") == subjects]
            if any(run.status == "running" for run in prior):
                self.stdout.write(self.style.WARNING(f"{court}: atualização já está ativa; evitando duplicidade"))
                continue
            resumable = next((run for run in prior if run.status in ("paused", "failed")), None)
            if resumable:
                self.stdout.write(f"{court}: continuando execução incremental {resumable.pk}")
                call_command("extract_datajud", resume=resumable.pk, max_pages=options["max_pages"])
                continue

            completed = next((run for run in prior if run.status == "completed" and run.finished_at), None)
            since = (
                completed.started_at - timedelta(days=options["overlap_days"])
                if completed
                else timezone.now() - timedelta(days=options["initial_lookback_days"])
            )
            self.stdout.write(f"{court}: buscando atualizações desde {since.isoformat()}")
            call_command(
                "extract_datajud",
                court=court,
                subjects=options["subjects"],
                page_size=options["page_size"],
                max_pages=options["max_pages"],
                updated_since=since.isoformat(),
            )
