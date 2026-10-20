import json
from datetime import date, datetime, timedelta, timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from src.api.datajud_client import DataJudClient, DataJudError
from src.db.models import ExtractionRun, RejectedRecord
from src.etl.loader import load_record
from src.etl.transformer import InvalidRecord, normalize


class Command(BaseCommand):
    help = "Extract public TJDFT or STJ metadata into the local dimensional warehouse."

    def add_arguments(self, parser):
        parser.add_argument("--start", default="2023-01-01")
        parser.add_argument("--end", default=date.today().isoformat())
        parser.add_argument("--court", choices=["TJDFT", "STJ"], default="TJDFT")
        parser.add_argument(
            "--subjects", default="10431", help="Exact CNJ codes; descendants are not inferred"
        )
        parser.add_argument("--page-size", type=int, default=100)
        parser.add_argument("--max-pages", type=int, default=5, help="Per invocation; 0 traverses all pages")
        parser.add_argument("--resume", type=int, help="Resume a paused/failed run using its saved scope")
        parser.add_argument("--updated-since", help="Incremental refresh by DataJud update timestamp (ISO date/time)")
        parser.add_argument(
            "--input", type=Path, help="Import a local DataJud JSON response as a partial sample"
        )

    def handle(self, *args, **options):
        if options["max_pages"] < 0:
            raise CommandError("--max-pages cannot be negative")
        if options["resume"] and (options["input"] or options["updated_since"]):
            raise CommandError("--resume cannot be combined with --input or --updated-since")
        imported = None
        if options["input"]:
            try:
                payload = json.loads(options["input"].read_text(encoding="utf-8-sig"))
                imported = payload["hits"]["hits"]
                if not isinstance(imported, list):
                    raise ValueError
            except (OSError, ValueError, KeyError, TypeError):
                raise CommandError("--input must contain a DataJud response with hits.hits") from None
        client = None
        resumed_matching_scope = False
        if options["resume"]:
            try:
                with transaction.atomic():
                    run = ExtractionRun.objects.get(pk=options["resume"])
                    if run.scope.get("origin") != "datajud":
                        raise CommandError("Only remote DataJud runs can be resumed")
                    claimed = ExtractionRun.objects.filter(pk=run.pk, status__in=["paused", "failed"]).update(
                        status="running",
                        error="",
                        finished_at=None,
                    )
                    if not claimed:
                        raise CommandError("Run must be paused/failed and cannot be running or complete")
                    run.refresh_from_db()
            except ExtractionRun.DoesNotExist:
                raise CommandError("Extraction run does not exist") from None
        else:
            try:
                subjects = sorted({int(code.strip()) for code in options["subjects"].split(",")})
                if not subjects or min(subjects) < 1 or not 1 <= options["page_size"] <= 1000:
                    raise ValueError
                update_mode = bool(options["updated_since"])
                if update_mode:
                    updated_since = datetime.fromisoformat(options["updated_since"].replace("Z", "+00:00"))
                    if timezone.is_naive(updated_since):
                        updated_since = updated_since.replace(tzinfo=dt_timezone.utc)
                    start, end = None, None
                else:
                    start, end = date.fromisoformat(options["start"]), date.fromisoformat(options["end"])
                    if start < date(2023, 1, 1) or start > end or end > date.today():
                        raise ValueError
            except ValueError:
                raise CommandError(
                    "Use valid dates from 2023 to today, positive subject codes and page-size 1..1000"
                ) from None
            scope = {
                "court": options["court"],
                "subject_codes": subjects,
                **({"update_mode": True, "updated_since": updated_since.isoformat()} if update_mode else {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "end_exclusive": (end + timedelta(days=1)).isoformat(),
                    "period_field": "dataAjuizamento",
                }),
                "page_size": options["page_size"],
                "origin": "file_sample" if imported is not None else "datajud",
                "subject_policy": "explicit_codes_only",
            }
            run = None
            if imported is None:
                candidates = ExtractionRun.objects.filter(
                    status__in=["paused", "failed"],
                    scope__court=options["court"],
                    scope__origin="datajud",
                ).order_by("-pk")
                for candidate in candidates:
                    if candidate.scope != scope:
                        continue
                    with transaction.atomic():
                        claimed = ExtractionRun.objects.filter(
                            pk=candidate.pk, status__in=["paused", "failed"]
                        ).update(status="running", error="", finished_at=None)
                        if claimed:
                            run = candidate
                            run.refresh_from_db()
                            resumed_matching_scope = True
                            break
            if run is None:
                run = ExtractionRun.objects.create(scope=scope)
        if imported is None:
            try:
                # A resumed STJ run must keep using its saved tribunal endpoint even
                # when --court is omitted from the resume command.
                client = DataJudClient(settings.DATAJUD_API_KEY, court=run.scope.get("court", "TJDFT"))
            except DataJudError as exc:
                raise CommandError(str(exc)) from None
        self.stdout.write(f"Run {run.pk}: {json.dumps(run.scope)}")
        if resumed_matching_scope:
            self.stdout.write("Resuming the paused/failed run for this exact scope from its saved cursor.")
        try:
            invocation_pages = 0
            while True:
                page = (
                    {"hits": imported, "total": {"value": len(imported), "relation": "eq"}}
                    if imported is not None
                    else client.search(run.scope, run.cursor)
                )
                hits = page["hits"]
                if not hits:
                    if "total" in page:
                        total = page["total"]
                        run.source_total = total.get("value") if isinstance(total, dict) else total
                        run.source_total_relation = (
                            total.get("relation", "") if isinstance(total, dict) else "eq"
                        )
                    run.status = "sample" if imported is not None else "completed"
                    break
                # Commit the whole page and cursor together: a failed page is retried safely.
                with transaction.atomic():
                    for hit in hits:
                        try:
                            record = normalize(hit, run.scope)
                            action = load_record(record, run)
                            setattr(run, action, getattr(run, action) + 1)
                        except InvalidRecord as exc:
                            run.rejected += 1
                            RejectedRecord.objects.create(
                                run=run, source_id=str(hit.get("_id", ""))[:255], reason=str(exc)
                            )
                        run.fetched += 1
                    run.pages += 1
                    run.cursor = hits[-1].get("sort") if imported is None else None
                    total = page.get("total", {})
                    run.source_total = total.get("value") if isinstance(total, dict) else total
                    run.source_total_relation = total.get("relation", "") if isinstance(total, dict) else "eq"
                    run.save()
                invocation_pages += 1
                self.stdout.write(
                    f"Page {run.pages}: fetched={run.fetched}, created={run.created}, updated={run.updated}, rejected={run.rejected}, stale={run.stale}"
                )
                if imported is not None:
                    run.status = "sample"
                    break
                if options["max_pages"] and invocation_pages >= options["max_pages"]:
                    run.status = "paused"
                    break
            run.finished_at = timezone.now()
            run.save()
        except (Exception, KeyboardInterrupt) as exc:
            # Reload counters because an exception may have rolled back the current page.
            run.refresh_from_db()
            run.status = "failed"
            run.finished_at = timezone.now()
            run.error = (
                str(exc)
                if isinstance(exc, DataJudError)
                else f"{type(exc).__name__}: ingestion interrupted; inspect locally and resume"
            )
            run.save()
            raise CommandError(f"Run {run.pk} failed: {run.error}") from None
        self.stdout.write(
            self.style.SUCCESS(
                f"Run {run.pk}: {run.status}. Records fetched: {run.fetched}; rejected: {run.rejected}."
            )
        )
        if run.status == "paused":
            self.stdout.write(
                f"Partial extraction. Continue: python manage.py extract_datajud --resume {run.pk} --max-pages 5"
            )
