"""Download STJ official full texts by publication date and explicit subject codes.

Provenance stays in PostgreSQL operational tables, texts in local staging.
Re-run the same command to resume completed publication batches.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import zipfile
from datetime import date, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import urlopen
from zoneinfo import ZoneInfo

CATALOG = (
    "https://dadosabertos.web.stj.jus.br/api/3/action/package_show"
    "?id=integras-de-decisoes-terminativas-e-acordaos-do-diario-da-justica"
)


def official(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "dadosabertos.web.stj.jus.br":
        raise ValueError("Expected official STJ open-data URL")
    return url


def download(url, target):
    for attempt in range(4):
        try:
            with urlopen(official(url), timeout=90) as response, target.open("wb") as output:
                official(response.url)
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            time.sleep(0.25)
            return
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 3:
                raise
            retry = exc.headers.get("Retry-After", "")
            time.sleep(min(float(retry), 30) if retry.isdigit() else 2**attempt)
        except (URLError, TimeoutError, OSError):
            if attempt == 3:
                raise
            time.sleep(2**attempt)


def read_json(url, directory):
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as handle:
        path = Path(handle.name)
    try:
        download(url, path)
        return json.loads(path.read_text(encoding="utf-8-sig"))
    finally:
        path.unlink(missing_ok=True)


def publication(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, ZoneInfo("America/Sao_Paulo")).date()
    return date.fromisoformat(str(value)[:10])


def run(args, directory):
    from django.db import transaction
    from django.utils import timezone

    from src.db.models import STJDocument, STJDocumentBatch, STJIngestionRun
    from src.etl.stj_ingestion import VERSION, persist_document

    scope = {"start": str(args.start), "end": str(args.end), "subjects": args.subjects}
    scope_hash = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
    ingestion = STJIngestionRun.objects.create(scope=scope, collector_version=VERSION, catalog_url=CATALOG)
    print(f"STJ ingestion run {ingestion.pk}", flush=True)
    try:
        collect(
            args,
            directory,
            scope,
            scope_hash,
            ingestion,
            persist_document,
            transaction,
            STJDocument,
            STJDocumentBatch,
        )
    except BaseException as exc:
        ingestion.refresh_from_db()
        ingestion.status = "failed"
        ingestion.finished_at = timezone.now()
        ingestion.errors = (ingestion.errors + [{"error": type(exc).__name__, "message": str(exc)[:500]}])[
            -100:
        ]
        ingestion.save()
        raise


def collect(
    args,
    directory,
    scope,
    scope_hash,
    ingestion,
    persist_document,
    transaction,
    STJDocument,
    STJDocumentBatch,
):
    from django.utils import timezone

    catalog = read_json(CATALOG, directory)
    if not catalog.get("success"):
        raise ValueError("STJ catalog request failed")
    ingestion.catalog_hash = hashlib.sha256(json.dumps(catalog, sort_keys=True).encode()).hexdigest()
    ingestion.source_license = {
        key: catalog["result"].get(key) for key in ("license_id", "license_title", "license_url")
    }
    ingestion.save()
    snapshots = directory / "catalogs"
    snapshots.mkdir(exist_ok=True)
    (snapshots / f"{ingestion.catalog_hash}.json").write_text(
        json.dumps(catalog, ensure_ascii=False), encoding="utf-8"
    )
    (directory / "source-catalog.json").write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    resources = {}
    for resource in catalog["result"]["resources"]:
        match = re.search(r"/(?:metadados|textos)?(\d{8})\.(json|zip)$", resource["url"])
        if match:
            day = datetime.strptime(match[1], "%Y%m%d").date()
            if args.start <= day <= args.end:
                resources.setdefault(day.isoformat(), {})[match[2]] = resource
    if not resources:
        raise ValueError("No official STJ publication batches available in requested period")
    completed = 0
    for day, batch in sorted(resources.items()):
        previous = STJDocumentBatch.objects.filter(scope_hash=scope_hash, publication_date=day).first()
        if (
            previous
            and not previous.scope.get("missing_document_ids")
            and not previous.scope.get("failed_records")
            and not getattr(args, "refresh", False)
        ):
            continue
        if "json" not in batch:
            raise ValueError(f"Missing metadata for STJ batch {day}")
        rows = read_json(batch["json"]["url"], directory)
        if not isinstance(rows, list):
            raise ValueError(f"Unexpected STJ metadata schema: {day}")
        selected = {}
        failures = []
        for row in rows:
            if not set(re.findall(r"\d+", str(row.get("assuntos", "")))).intersection(args.subjects):
                continue
            try:
                if not args.start <= publication(row["dataPublicacao"]) <= args.end:
                    continue
                identifier = str(row["seqDocumento"])
                if not identifier.isascii() or not identifier.isdigit() or len(identifier) > 64:
                    raise ValueError("Invalid STJ document identifier")
            except (KeyError, ValueError, TypeError, OverflowError) as exc:
                failures.append({"id": str(row.get("seqDocumento", ""))[:64], "error": type(exc).__name__})
                continue
            selected[identifier] = row
        missing = set()
        payloads = {}
        archive_url = batch.get("zip", {}).get("url", "")
        if selected:
            archive = directory / "batch.zip.part"
            try:
                if archive_url:
                    try:
                        download(archive_url, archive)
                    except HTTPError as exc:
                        if exc.code not in {403, 404, 410}:
                            raise
                        archive_url = ""
                if archive_url:
                    with zipfile.ZipFile(archive) as zipped:
                        for member in zipped.infolist():
                            identifier = Path(member.filename).stem
                            if member.is_dir() or identifier not in selected:
                                continue
                            suffix = Path(member.filename).suffix.lower()
                            if suffix not in {".txt", ".pdf"}:
                                continue
                            payload = zipped.read(member)  # validates CRC; never extract archive paths
                            if payload:
                                payloads[identifier] = (payload, suffix)
                missing = set(selected) - set(payloads)
            finally:
                archive.unlink(missing_ok=True)
        input_failed = len(failures)
        with transaction.atomic():
            for identifier, row in selected.items():
                payload, suffix = payloads.get(identifier, (None, ".txt"))
                try:
                    action, unavailable = persist_document(
                        row,
                        payload,
                        suffix,
                        batch["json"]["url"],
                        batch.get("zip", {}).get("url", ""),
                        directory,
                        ingestion,
                    )
                    setattr(ingestion, action, getattr(ingestion, action) + 1)
                    ingestion.unavailable += int(unavailable)
                except (ValueError, TypeError, KeyError, OverflowError) as exc:
                    failures.append({"id": identifier, "error": type(exc).__name__})
            ingestion.retrieved += len(selected) + input_failed
            ingestion.failed += len(failures)
            ingestion.batches += 1
            ingestion.errors = (ingestion.errors + [{"day": day, **failure} for failure in failures])[-100:]
            ingestion.save()
            STJDocumentBatch.objects.update_or_create(
                scope_hash=scope_hash,
                publication_date=day,
                defaults={
                    "scope": {
                        **scope,
                        "missing_document_ids": sorted(missing),
                        "failed_records": failures,
                        "source_rows": len(rows),
                        "selected_rows": len(selected),
                        "metadata_url": batch["json"]["url"],
                        "archive_url": batch.get("zip", {}).get("url", ""),
                    },
                    "last_run": ingestion,
                },
            )
        completed += 1
        print(
            f"STJ {day}: matched={len(selected)}; missing={len(missing)}; stored_records={STJDocument.objects.count()}",
            flush=True,
        )
        if args.max_batches and completed >= args.max_batches:
            ingestion.status = "paused"
            ingestion.finished_at = timezone.now()
            ingestion.save()
            print("PAUSED: batch limit reached; repeat the same command to resume.", flush=True)
            return
    pending = sum(
        bool(batch.scope.get("missing_document_ids") or batch.scope.get("failed_records"))
        for batch in STJDocumentBatch.objects.filter(scope_hash=scope_hash)
    )
    ingestion.status = "partial" if pending else "completed"
    ingestion.finished_at = timezone.now()
    ingestion.save()
    print(
        f"{'PARTIAL' if pending else 'COMPLETED'}: {len(resources)} catalog publication batches in period; pending_batches={pending}; stored_records={STJDocument.objects.count()}. Available catalog only; not a completeness claim.",
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2016, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--subjects", default="10431,10433,10439")
    parser.add_argument("--max-batches", type=int, default=0)
    parser.add_argument(
        "--refresh", action="store_true", help="Re-read completed batches to acquire source revisions"
    )
    args = parser.parse_args()
    if args.start > args.end or args.max_batches < 0:
        parser.error("Invalid date range or batch limit")
    args.subjects = sorted({str(int(code)) for code in args.subjects.split(",")})
    from dotenv import load_dotenv

    etl_dir = Path(__file__).resolve().parent
    load_dotenv(etl_dir / ".env", override=False)
    sys.path.insert(0, str(etl_dir.parent / "backend"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    directory = Path(__file__).resolve().parent / "data" / "stj-documents"
    (directory / "texts").mkdir(parents=True, exist_ok=True)
    # OS releases this lock even after an interrupted or killed process.
    import msvcrt

    with (directory / "collector.lock").open("a+b") as lock:
        lock.seek(0)
        if lock.read(1) == b"":
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise SystemExit("Another STJ document collector is active") from None
        run(args, directory)


if __name__ == "__main__":
    main()
