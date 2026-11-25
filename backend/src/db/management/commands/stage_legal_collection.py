"""Stage the pinned phase 3A metadata for human review in the local operational database."""

import json
from collections import Counter
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from src.db.civil_subjects import ROOT, branch_codes
from src.db.models import LegalCorpusItem, LegalCorpusTopicMatch, LegalReference
from src.nlp.topics import TOPICS
from src.services.corpus_catalog import safe_url
from src.services.publication_manifest import digest, is_sha256

DATABASE = "datumlex_ops_f3_full"
COUNTS = {"jurisprudence": 4, "precedent": 2, "doctrine": 2}
TOPIC_IDS = {key for key, _, _ in TOPICS}


def staged_items(path, expected):
    package = json.loads(path.read_text(encoding="utf-8"))
    integrity = package.pop("integrity")
    if not is_sha256(expected) or integrity["payload_sha256"] != expected or digest(package) != expected:
        raise ValueError("package_hash")
    rows = package["items"]
    if (package["schema_version"] != 1 or package["collection_id"] != "datumlex-responsabilidade-civil-real"
            or package["collection_version"] != "0.1.0" or package["synthetic"] is not False
            or package["scope"]["tpu_root"] != ROOT or Counter(row["category"] for row in rows) != COUNTS
            or len({row["id"] for row in rows}) != len(rows)):
        raise ValueError("package_scope")
    for row in rows:
        if (row["review_status"] != "pending" or row["public_release"] is not False
                or row["identity_verification"] != "verified_official" or row["metadata_stage_ready"] is not True
                or not safe_url(row["source_url"]) or not row["source_locator"]
                or row["nlp"]["product_processing_released"] is not False
                or row["citation"]["gemini_released"] is not False
                or not set(row["tpu"]["codes"]) <= branch_codes(ROOT)
                or digest({key: value for key, value in row.items() if key != "metadata_sha256"}) != row["metadata_sha256"]):
            raise ValueError("item_scope")
    return package, rows


class Command(BaseCommand):
    help = "Stage only the reviewed package structure. All rows remain pending."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--package", type=Path, required=True)
        parser.add_argument("--sha256", required=True)

    def handle(self, **options):
        if (connection.vendor != "postgresql" or connection.settings_dict["NAME"] != DATABASE
                or connection.settings_dict["HOST"] not in ("", "localhost", "127.0.0.1", "::1")):
            raise CommandError("Use exclusivamente o PostgreSQL operacional local da Fase 3.")
        expected = options["sha256"]
        try:
            package, rows = staged_items(options["package"], expected)
        except (OSError, ValueError, KeyError, TypeError):
            raise CommandError("Pacote de revisão inválido ou divergente do SHA-256 fixado.") from None
        added = Counter()
        with transaction.atomic(durable=True), connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), pg_try_advisory_xact_lock(3045183)")
            if cursor.fetchone() != (DATABASE, True):
                raise CommandError("O destino local não está disponível para esta carga.")
            for row in rows:
                provenance = {"collection": package["collection_id"], "version": package["collection_version"],
                              "package_sha256": expected, "permissions": {},
                              "metadata": row}
                category = row["category"]
                day = date.fromisoformat(row["date"]) if row["date"] else None
                bibliography = row["bibliography"] or {}
                authority = row["authority"] or {}
                origin = (row["archive_provenance"] or {}).get("origin_key") or "source:" + row["id"]
                if category != "jurisprudence":
                    codes = row["tpu"]["codes"]
                    reference, created = LegalReference.objects.get_or_create(
                        source_name=row["issuer"], identifier=row["id"],
                        defaults={"reference_type": category, "source_institution": (
                            "Senado" if category == "doctrine" else row["issuer"]),
                            "title": row["title"], "thesis": "", "approved": False, "approval_reference": "",
                            "source_url": row["source_url"], "source_locator": row["source_locator"],
                            "authority": authority.get("kind", ""),
                            "subject_code": codes[0] if len(codes) == 1 else None,
                            "published_at": day if row["date_kind"] == "publication_date" else None,
                            "source_payload_hash": row["metadata_sha256"], "source_metadata": provenance,
                            "related_decisions": [{"identifier": name} for name in authority.get("paradigms", [])]},
                    )
                    if (reference.source_payload_hash != row["metadata_sha256"] or reference.approved
                            or reference.reference_type != category or reference.source_metadata != provenance or reference.thesis):
                        raise CommandError("Referência existente diverge da versão pendente. Carga revertida.")
                    added["legal_references"] += int(created)
                    origin = f"reference:{reference.pk}"
                    provenance = {**provenance, "reference_id": reference.pk}
                item, created = LegalCorpusItem.objects.get_or_create(
                    origin_key=origin,
                    defaults={"category": category, "court": "" if category == "doctrine" else row["issuer"],
                              "title": row["title"], "source_name": row["issuer"], "source_url": row["source_url"],
                              "content_kind": row["source_kind"], "date": day, "date_kind": row["date_kind"],
                              "authors": bibliography.get("authors", []), "review_status": "pending", "excerpt": "",
                              "fingerprint": row["metadata_sha256"], "provenance": provenance},
                )
                if (item.fingerprint != row["metadata_sha256"] or item.review_status != "pending"
                        or item.category != category or item.provenance != provenance or item.excerpt):
                    raise CommandError("Item existente diverge da versão pendente. Carga revertida.")
                added[category] += int(created)
                for topic in sorted(set(row["topics"]) & TOPIC_IDS):
                    _, created = LegalCorpusTopicMatch.objects.get_or_create(
                        item=item, topic=topic, defaults={"method": "editorial_candidate_3a", "matched_terms": []},
                    )
                    added["topic_links"] += int(created)
        self.stdout.write(json.dumps({"database": DATABASE, "status": "pending", "package_sha256": expected,
                                      "processed": COUNTS, "created": dict(added)}, sort_keys=True))
