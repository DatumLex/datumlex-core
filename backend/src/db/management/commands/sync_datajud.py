from datetime import date

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from src.db.models import ExtractionRun
from src.db.subject_catalog import DEFAULT_DATAJUD_SUBJECT_CODES_CSV
from src.services.period import HISTORY_START, today
from src.db.court_catalog import ACTIVE_COURTS as COURTS


class Command(BaseCommand):
    help = "Bootstrap TJDFT/STJ history, resume partial loads, then refresh both courts incrementally."

    def add_arguments(self, parser):
        parser.add_argument('--court', choices=COURTS, help='Optional single-court batch')
        parser.add_argument("--start", default=HISTORY_START.isoformat())
        parser.add_argument("--subjects", default=DEFAULT_DATAJUD_SUBJECT_CODES_CSV)
        parser.add_argument("--page-size", type=int, default=100)
        parser.add_argument("--max-pages", type=int, default=2)
        parser.add_argument("--overlap-days", type=int, default=3)
        parser.add_argument("--initial-lookback-days", type=int, default=30)

    def handle(self, *args, **options):
        try:
            start = date.fromisoformat(options["start"])
            subjects = sorted({int(code.strip()) for code in options["subjects"].split(",")})
            if start < HISTORY_START or start > today() or not subjects or min(subjects) < 1:
                raise ValueError
        except ValueError:
            raise CommandError("Use a valid start date from 2016 to today and positive subject codes") from None
        if options["max_pages"] < 1 or not 1 <= options["page_size"] <= 1000:
            raise CommandError("Use max-pages >= 1 and page-size 1..1000")

        bootstrap_complete = True
        history_attempted = False
        for court in ([options['court']] if options.get('court') else ("TJDFT", "STJ")):
            candidates = ExtractionRun.objects.filter(
                scope__origin="datajud",
                scope__court=court,
                scope__start=start.isoformat(),
            ).order_by("-started_at", "-pk")
            matching_runs = [
                run for run in candidates
                if run.scope.get("subject_codes") == subjects and not run.scope.get("update_mode")
            ]
            already_running = next((run for run in matching_runs if run.status == "running"), None)
            resumable = next((run for run in matching_runs if run.status in ("paused", "failed")), None)
            completed = any(run.status == "completed" for run in matching_runs)

            if already_running:
                self.stdout.write(self.style.WARNING(
                    f"{court}: execução histórica {already_running.pk} já está ativa; evitando duplicidade"
                ))
                bootstrap_complete = False
            elif resumable:
                history_attempted = True
                self.stdout.write(f"{court}: retomando carga histórica {resumable.pk}")
                call_command("extract_datajud", resume=resumable.pk, max_pages=options["max_pages"])
                resumable.refresh_from_db()
                bootstrap_complete &= resumable.status == "completed"
            elif completed:
                self.stdout.write(f"{court}: carga histórica desde {start.isoformat()} já concluída")
            else:
                history_attempted = True
                self.stdout.write(f"{court}: iniciando carga histórica desde {start.isoformat()}")
                call_command(
                    "extract_datajud",
                    court=court,
                    start=start.isoformat(),
                    subjects=options["subjects"],
                    page_size=options["page_size"],
                    max_pages=options["max_pages"],
                )
                recent_runs = ExtractionRun.objects.filter(
                    scope__origin="datajud", scope__court=court, scope__start=start.isoformat()
                ).order_by("-started_at", "-pk")
                latest = next((
                    run for run in recent_runs
                    if run.scope.get("subject_codes") == subjects and not run.scope.get("update_mode")
                ), None)
                bootstrap_complete &= bool(latest and latest.status == "completed")

        if not bootstrap_complete:
            self.stdout.write(self.style.WARNING(
                "Carga histórica parcial; a próxima execução continuará do cursor salvo. "
                "A atualização incremental começará quando TJDFT e STJ concluírem o histórico."
            ))
            return

        if history_attempted:
            self.stdout.write("Histórico concluído; atualização incremental fica para a próxima execução, preservando o limite do lote.")
            return

        self.stdout.write("Histórico concluído nos dois tribunais; atualizando registros recentes.")
        call_command(
            "refresh_datajud",
            court=options.get('court'),
            subjects=options["subjects"],
            page_size=options["page_size"],
            max_pages=options["max_pages"],
            overlap_days=options["overlap_days"],
            initial_lookback_days=options["initial_lookback_days"],
        )
