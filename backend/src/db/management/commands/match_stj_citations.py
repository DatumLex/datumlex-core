from django.core.management.base import BaseCommand
from django.db import transaction

from src.db.models import CrossSourceLinkCandidate, FactProcess, LegalReference
from src.etl.cross_source_matching import MATCHER_VERSION, candidate_key, normalize_cnj_identifier


def _citation(value):
    if isinstance(value, dict):
        identifier = next((
            value.get(key) for key in ("identifier", "numeroProcesso", "numero", "processo")
            if value.get(key)
        ), "")
        locator = value.get("locator") or value.get("source_locator") or ""
        return str(identifier).strip(), str(locator).strip()
    return str(value).strip() if value else "", ""


class Command(BaseCommand):
    help = "Reconcile explicitly cited STJ decisions with TJDFT records by exact CNJ identifier."

    @transaction.atomic
    def handle(self, *args, **options):
        local_by_number = {}
        local_records = FactProcess.objects.filter(court="TJDFT").values_list(
            "id", "source_id", "process_dimension__number_process"
        )
        for local_id, source_id, number in local_records.iterator():
            normalized = normalize_cnj_identifier(number)
            if normalized:
                local_by_number.setdefault(normalized, []).append((local_id, source_id))

        references = LegalReference.objects.filter(
            reference_type=LegalReference.PRECEDENT,
            source_institution="STJ",
        ).only("id", "identifier", "source_url", "source_locator", "related_decisions")
        created = resolved = unresolved = 0
        for reference in references.iterator():
            citations = reference.related_decisions
            if not isinstance(citations, list):
                continue
            for citation in citations:
                cited_identifier, citation_locator = _citation(citation)
                if not cited_identifier:
                    continue
                normalized = normalize_cnj_identifier(cited_identifier)
                local_matches = local_by_number.get(normalized, []) if normalized else []
                locator = citation_locator or reference.source_locator
                if local_matches:
                    CrossSourceLinkCandidate.objects.filter(
                        candidate_key=candidate_key(reference.pk, cited_identifier),
                        review_status=CrossSourceLinkCandidate.UNRESOLVED,
                    ).update(review_status=CrossSourceLinkCandidate.SUPERSEDED)
                    for local_id, local_source_id in local_matches:
                        key = candidate_key(reference.pk, "matched", local_source_id)
                        _, was_created = CrossSourceLinkCandidate.objects.get_or_create(
                            candidate_key=key,
                            defaults={
                                "local_decision_id": local_id,
                                "reference": reference,
                                "relationship_type": "source_cited_decision",
                                "cited_identifier": cited_identifier[:200],
                                "normalized_identifier": normalized,
                                "method": "exact_cnj_identifier",
                                "method_version": MATCHER_VERSION,
                                "confidence": "1.0000",
                                "review_status": CrossSourceLinkCandidate.PENDING,
                                "source_locator": locator[:500],
                                "explanation": (
                                    "Identificador CNJ completo da decisão citada corresponde exatamente "
                                    "ao processo TJDFT. A correspondência identifica o registro, não "
                                    "relação jurídica, aderência ou aplicabilidade do precedente."
                                ),
                            },
                        )
                        created += int(was_created)
                        resolved += 1
                else:
                    method = "exact_cnj_identifier" if normalized else "unresolved_identifier"
                    reason = (
                        "Identificador CNJ completo não encontrado nos registros TJDFT locais."
                        if normalized else
                        "A fonte informa citação que não contém um CNJ completo; o texto TJDFT "
                        "ainda não está disponível para resolução por citação."
                    )
                    key = candidate_key(reference.pk, cited_identifier)
                    _, was_created = CrossSourceLinkCandidate.objects.get_or_create(
                        candidate_key=key,
                        defaults={
                            "local_decision": None,
                            "reference": reference,
                            "relationship_type": "source_cited_decision",
                            "cited_identifier": cited_identifier[:200],
                            "normalized_identifier": normalized,
                            "method": method,
                            "method_version": MATCHER_VERSION,
                            "confidence": None,
                            "review_status": CrossSourceLinkCandidate.UNRESOLVED,
                            "source_locator": locator[:500],
                            "explanation": reason,
                        },
                    )
                    created += int(was_created)
                    unresolved += 1

        self.stdout.write(self.style.SUCCESS(
            f"Reconciliação concluída: {created} candidatos novos, "
            f"{resolved} vínculos exatos de identidade, {unresolved} citações não resolvidas. "
            "Nenhum candidato altera indicadores de aderência/divergência."
        ))
