from django.core.management import call_command
from django.core.management.base import BaseCommand

from src.db.models import ExtractionRun


TARGET = {
    "court": "TJDFT",
    "subject_codes": [10431, 10433, 10439],
    "start": "2023-01-01",
    "end": "2026-09-27",
    "origin": "datajud",
}


def matches_target(run):
    scope = run.scope
    return all(scope.get(key) == value for key, value in TARGET.items())


class Command(BaseCommand):
    help = "Load the deployment DataJud scope once, resuming an interrupted extraction when possible."

    def handle(self, *args, **options):
        runs = list(ExtractionRun.objects.order_by("-pk"))
        if any(run.status == "completed" and matches_target(run) for run in runs):
            self.stdout.write(self.style.SUCCESS("DataJud deployment scope is already loaded."))
            return

        resumable = next(
            (
                run
                for run in runs
                if run.status in {"paused", "failed"} and matches_target(run)
            ),
            None,
        )
        common = {"max_pages": 0, "stdout": self.stdout, "stderr": self.stderr}
        if resumable:
            self.stdout.write(f"Resuming DataJud extraction run {resumable.pk}.")
            call_command("extract_datajud", resume=resumable.pk, **common)
            return

        self.stdout.write("Loading the DataJud deployment scope.")
        call_command(
            "extract_datajud",
            start=TARGET["start"],
            end=TARGET["end"],
            subjects=",".join(str(code) for code in TARGET["subject_codes"]),
            page_size=1000,
            **common,
        )
