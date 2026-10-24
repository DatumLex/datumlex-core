from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from src.db.models import ExtractionRun
from src.db.subject_catalog import DEFAULT_DATAJUD_SUBJECT_CODES_CSV


class Command(BaseCommand):
    help = "Incrementally refresh TJDFT and STJ DataJud records for the dashboard."

    def add_arguments(self, parser):
        parser.add_argument("--subjects", default=DEFAULT_DATAJUD_SUBJECT_CODES_CSV)
        parser.add_argument("--page-size", type=int, default=100)
        parser.add_argument("--max-pages", type=int, default=5)
        parser.add_argument("--overlap-days", type=int, default=3)
        parser.add_argument("--initial-lookback-days", type=int, default=30)

    def handle(self, *args, **options):
        if options["max_pages"] < 1 or options["overlap_days"] < 0 or options["initial_lookback_days"] < 1:
            raise CommandError("Use max-pages >= 1, overlap-days >= 0 and initial-lookback-days >= 1")

        for court in ("TJDFT", "STJ"):
            prior = ExtractionRun.objects.filter(
                scope__origin="datajud",
                scope__court=court,
                scope__update_mode=True,
            ).order_by("-started_at", "-pk")
            resumable = prior.filter(status__in=["paused", "failed"]).first()
            if resumable:
                self.stdout.write(f"{court}: continuando execução incremental {resumable.pk}")
                call_command("extract_datajud", resume=resumable.pk, max_pages=options["max_pages"])
                continue

            completed = prior.filter(status="completed", finished_at__isnull=False).first()
            since = (
                completed.finished_at - timedelta(days=options["overlap_days"])
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
