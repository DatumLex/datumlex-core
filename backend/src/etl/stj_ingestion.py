"""Auditable STJ publications, separate from the document-grain analytical fact."""

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from django.db import transaction

from src.db.models import STJDocument, STJDocumentVersion

VERSION = "stj-publications-v2"


def publication(value):
    if isinstance(value, bool):
        raise ValueError("Invalid publication date")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, ZoneInfo("America/Sao_Paulo")).date()
    return date.fromisoformat(str(value)[:10])


def optional_text(row, *keys, maximum=255):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)[:maximum]
    return None


@transaction.atomic
def persist_document(row, payload, suffix, metadata_url, archive_url, directory, run):
    identity = str(row["seqDocumento"])
    if not identity.isascii() or not identity.isdigit() or len(identity) > 64:
        raise ValueError("Invalid STJ source ID")
    status = "available" if payload is not None else "unavailable"
    content_hash = hashlib.sha256(payload).hexdigest() if payload is not None else ""
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "metadata": row,
                "sha256": content_hash,
                "status": status,
                "metadata_url": metadata_url,
                "archive_url": archive_url,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    existing = STJDocument.objects.filter(source_id=identity).first()
    if payload is None and existing and existing.text_status == "available":
        # A transiently missing source archive must not discard an already acquired text.
        return "duplicates", True
    path = ""
    if payload is not None:
        if suffix not in {".txt", ".pdf"}:
            raise ValueError("Unsupported STJ text format")
        target = Path(directory) / "texts" / f"{identity}-{content_hash}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != content_hash:
            temporary = target.with_suffix(suffix + ".part")
            temporary.write_bytes(payload)
            temporary.replace(target)
        path = target.relative_to(directory).as_posix()
    decision = row.get("dataJulgamento")
    fields = {
        "publication_date": publication(row["dataPublicacao"]),
        "decision_date": publication(decision) if decision not in (None, "") else None,
        "panel": optional_text(row, "orgaoJulgador", "nomeOrgaoJulgador"),
        "precedent_type": optional_text(row, "tipoPrecedente", maximum=100),
        "precedent_status": optional_text(row, "situacaoPrecedente", "statusPrecedente", maximum=100),
        "metadata": row,
        "metadata_url": metadata_url,
        "archive_url": archive_url,
        "local_path": path,
        "sha256": content_hash,
        "text_status": status,
        "last_run": run,
    }
    document, created = STJDocument.objects.update_or_create(source_id=identity, defaults=fields)
    _, version_created = STJDocumentVersion.objects.get_or_create(
        document=document,
        fingerprint=fingerprint,
        defaults={
            "run": run,
            "metadata": row,
            "metadata_url": metadata_url,
            "archive_url": archive_url,
            "local_path": path,
            "sha256": content_hash,
            "text_status": status,
        },
    )
    return ("created" if created else "updated" if version_created else "duplicates"), payload is None
