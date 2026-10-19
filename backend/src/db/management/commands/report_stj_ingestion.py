"""Reconcile source observations, current records, versions and local file integrity."""

import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

from src.db.models import STJDocument, STJDocumentBatch, STJDocumentVersion, STJIngestionRun


class Command(BaseCommand):
    help = "Produce STJ ingestion reconciliation and field coverage; excludes full text and credentials."

    def add_arguments(self, parser):
        parser.add_argument("--output", type=Path)
        parser.add_argument("--verify-files", action="store_true")

    def handle(self, *args, **options):
        documents = STJDocument.objects.all()
        root = settings.BASE_DIR.parent / "etl" / "data" / "stj-documents"
        integrity = {"checked": 0, "missing": [], "hash_mismatch": [], "unsafe_path": []}
        if options["verify_files"]:
            for document in documents.filter(text_status="available").iterator():
                integrity["checked"] += 1
                path = (root / document.local_path).resolve()
                if not path.is_relative_to(root.resolve()):
                    integrity["unsafe_path"].append(document.source_id)
                elif not path.is_file():
                    integrity["missing"].append(document.source_id)
                elif hashlib.sha256(path.read_bytes()).hexdigest() != document.sha256:
                    integrity["hash_mismatch"].append(document.source_id)
        runs = []
        for run in STJIngestionRun.objects.order_by("id"):
            counts = {
                key: getattr(run, key)
                for key in (
                    "retrieved",
                    "created",
                    "updated",
                    "duplicates",
                    "failed",
                    "unavailable",
                    "batches",
                )
            }
            runs.append(
                {
                    "id": run.pk,
                    "status": run.status,
                    "scope": run.scope,
                    "collector_version": run.collector_version,
                    "catalog_hash": run.catalog_hash,
                    "license": run.source_license,
                    **counts,
                    "reconciled": run.retrieved == run.created + run.updated + run.duplicates + run.failed,
                    "errors": run.errors,
                }
            )
        fields = ("publication_date", "decision_date", "panel", "precedent_type", "precedent_status")
        report = {
            "generated_at": timezone.now().isoformat(),
            "source": "Official STJ open-data publication catalog",
            "unit": "STJ seqDocumento; source-selected records, separate from DataJud process facts",
            "runs": runs,
            "current_records": documents.count(),
            "text_status": list(documents.values("text_status").annotate(total=Count("pk"))),
            "versions": STJDocumentVersion.objects.count(),
            "field_coverage": {
                field: {
                    "available": documents.exclude(**{field: None}).count(),
                    "unavailable": documents.filter(**{field: None}).count(),
                }
                for field in fields
            },
            "pending_batches": [
                {
                    "date": batch.publication_date.isoformat(),
                    "missing_document_ids": batch.scope.get("missing_document_ids", []),
                    "failed_records": batch.scope.get("failed_records", []),
                    "metadata_url": batch.scope.get("metadata_url"),
                    "archive_url": batch.scope.get("archive_url"),
                }
                for batch in STJDocumentBatch.objects.all()
                if batch.scope.get("missing_document_ids") or batch.scope.get("failed_records")
            ],
            "sample": list(
                documents.order_by("source_id").values(
                    "source_id",
                    "publication_date",
                    "decision_date",
                    "panel",
                    "precedent_type",
                    "precedent_status",
                    "text_status",
                    "metadata_url",
                    "archive_url",
                    "sha256",
                )[:5]
            ),
            "file_integrity": integrity,
            "limitations": [
                "Publication date is not filing date",
                "No automatic precedent authority inference",
                "Null means source field unavailable",
                "Catalog traversal is not proof of full STJ coverage",
            ],
        }
        rendered = json.dumps(report, ensure_ascii=False, indent=2, default=str)
        if options["output"]:
            options["output"].parent.mkdir(parents=True, exist_ok=True)
            options["output"].write_text(rendered + "\n", encoding="utf-8")
            self.stdout.write(f"STJ report: {options['output']}")
        else:
            self.stdout.write(rendered)
