"""Establish a verified current baseline; never invent historical versions."""

import hashlib

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from src.db.models import STJDocument, STJIngestionRun
from src.etl.stj_ingestion import VERSION, persist_document


class Command(BaseCommand):
    help = "Register a current, hash-verified version of legacy STJ texts; no network calls."

    def handle(self, *args, **options):
        root = settings.BASE_DIR.parent / "etl" / "data" / "stj-documents"
        run = STJIngestionRun.objects.create(
            scope={
                "mode": "existing-local-snapshot",
                "court": "STJ",
                "limitation": "Current verified baseline; no reconstruction of unrecorded past versions",
            },
            collector_version=VERSION,
            catalog_url="https://dadosabertos.web.stj.jus.br/api/3/action/package_show?id=integras-de-decisoes-terminativas-e-acordaos-do-diario-da-justica",
        )
        try:
            for document in STJDocument.objects.filter(versions__isnull=True).iterator():
                run.retrieved += 1
                path = (root / document.local_path).resolve()
                if not path.is_relative_to(root.resolve()) or not path.is_file():
                    run.failed += 1
                    run.errors = (
                        run.errors + [{"id": document.source_id, "error": "local_file_missing_or_unsafe"}]
                    )[-100:]
                else:
                    payload = path.read_bytes()
                    if hashlib.sha256(payload).hexdigest() != document.sha256:
                        run.failed += 1
                        run.errors = (
                            run.errors + [{"id": document.source_id, "error": "local_hash_mismatch"}]
                        )[-100:]
                    else:
                        action, unavailable = persist_document(
                            document.metadata,
                            payload,
                            path.suffix.lower(),
                            document.metadata_url,
                            document.archive_url,
                            root,
                            run,
                        )
                        setattr(run, action, getattr(run, action) + 1)
                        run.unavailable += int(unavailable)
                run.save()
            run.status = "partial" if run.failed else "completed"
        except BaseException:
            run.status = "failed"
            raise
        finally:
            run.finished_at = timezone.now()
            run.save()
        self.stdout.write(
            f"Baseline run {run.pk}: {run.status}, observed={run.retrieved}, updated={run.updated}, failed={run.failed}"
        )
