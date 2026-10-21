import json
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from src.db.models import DecisionAssessment, FactProcess, LegalReference


class Command(BaseCommand):
    help = "Import a sourced, approval-tracked precedent/doctrine corpus and reviewed TJDFT mappings."

    def add_arguments(self, parser):
        parser.add_argument("--input", required=True, type=Path)

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            payload = json.loads(options["input"].read_text(encoding="utf-8-sig"))
            references = payload["references"]
            if not isinstance(references, list):
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError):
            raise CommandError("--input must be a JSON file with a references array") from None

        saved_references = saved_assessments = 0
        for item in references:
            try:
                approval = str(item["approval_reference"]).strip()
                approved = item["approved"]
                source_name = str(item["source_name"]).strip()
                institution = item["source_institution"]
                identifier = str(item["identifier"]).strip()
                title = str(item["title"]).strip()
                thesis = str(item["thesis"]).strip()
                source_url = str(item["source_url"]).strip()
                source_locator = str(item["source_locator"]).strip()
                if (
                    not isinstance(approved, bool)
                    or item["reference_type"] not in dict(LegalReference.SOURCE_TYPES)
                    or institution not in dict(LegalReference.SOURCE_INSTITUTIONS)
                    or (item["reference_type"] == LegalReference.PRECEDENT and institution != "STJ")
                    or (item["reference_type"] == LegalReference.DOCTRINE and institution != "BDJur")
                    or not approval or not source_name or not identifier or not title or not thesis
                    or not source_locator or urlparse(source_url).scheme != "https"
                    or not urlparse(source_url).netloc
                ):
                    raise ValueError
                subject_code = item.get("subject_code")
                if subject_code is not None and (isinstance(subject_code, bool) or int(subject_code) < 1):
                    raise ValueError
                published = date.fromisoformat(item["published_at"]) if item.get("published_at") else None
                ref, _ = LegalReference.objects.update_or_create(
                    source_name=source_name,
                    identifier=identifier,
                    defaults={
                        "reference_type": item["reference_type"],
                        "source_institution": institution,
                        "title": title,
                        "thesis": thesis,
                        "authority": item.get("authority", ""),
                        "source_url": source_url,
                        "source_locator": source_locator,
                        "subject_code": int(subject_code) if subject_code is not None else None,
                        "published_at": published,
                        "approval_reference": approval,
                        "approved": approved,
                    },
                )
            except (KeyError, TypeError, ValueError):
                raise CommandError("Each reference needs valid type, identifier, title, thesis, source URL and approval reference") from None
            saved_references += 1

            for mapping in item.get("assessments", []):
                if ref.reference_type != LegalReference.PRECEDENT or ref.source_institution != "STJ":
                    raise CommandError("Only STJ precedents may be mapped to an adherence assessment; BDJur doctrine is retained as supporting source material")
                try:
                    decision = FactProcess.objects.get(
                        court="TJDFT", source_id=str(mapping["local_source_id"])
                    )
                    relation = mapping["relation"]
                    state = mapping["review_state"]
                    decision_date = date.fromisoformat(mapping["decision_date"])
                    rationale = str(mapping["rationale"]).strip()
                    reviewer = str(mapping.get("reviewer", "")).strip()
                    mapping_approval = str(mapping.get("approval_reference", "")).strip()
                    if relation not in dict(DecisionAssessment.RELATIONS) or state not in dict(DecisionAssessment.REVIEW_STATES) or not rationale:
                        raise ValueError
                    if state == DecisionAssessment.REVIEW_APPROVED and (
                        not reviewer or not mapping_approval
                        or not str(mapping.get("evidence_excerpt", "")).strip()
                        or not str(mapping.get("evidence_locator", "")).strip()
                    ):
                        raise ValueError
                    defaults = {
                        "relation": relation,
                        "review_state": state,
                        "decision_date": decision_date,
                        "rationale": rationale,
                        "evidence_excerpt": mapping.get("evidence_excerpt", ""),
                        "evidence_locator": mapping.get("evidence_locator", ""),
                        "reviewer": reviewer,
                        "reviewed_at": timezone.now() if state != DecisionAssessment.PENDING else None,
                        "approval_reference": mapping_approval,
                    }
                    DecisionAssessment.objects.update_or_create(
                        local_decision=decision, reference=ref, defaults=defaults
                    )
                except (FactProcess.DoesNotExist, KeyError, TypeError, ValueError):
                    raise CommandError(
                        "Each assessment needs an existing TJDFT local_source_id, decision date, relation, review state and rationale; validated entries also need reviewer and approval reference"
                    ) from None
                saved_assessments += 1

        self.stdout.write(self.style.SUCCESS(
            f"Imported {saved_references} references and {saved_assessments} decision assessments. Only approved references and validated assessments enter dashboard indicators."
        ))
