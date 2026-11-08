from django.db.models import Q

from src.db.models import LegalReference


def report_references(scope):
    inventory = LegalReference.objects.filter(
        source_institution__in=scope["court"].split(","),
        last_import_run__isnull=False,
        source_name__startswith="Pangea",
    )
    if not inventory.exists():
        return None
    if scope["subject"]:
        inventory = inventory.filter(Q(subject_code=scope["subject"]) | Q(subject_code__isnull=True))
    dated = inventory.filter(published_at__range=[scope["start"], scope["end"]])
    undated = inventory.filter(published_at__isnull=True)
    candidates = inventory.filter(
        Q(published_at__range=[scope["start"], scope["end"]]) | Q(published_at__isnull=True)
    )
    return {
        "inventory_count": inventory.count(),
        "dated_count": dated.count(),
        "undated_count": undated.count(),
        "unmapped_subject_count": inventory.filter(subject_code__isnull=True).count(),
        "sample_count": candidates.count(),
        "items": list(
            candidates.order_by("-approved", "-source_updated_at", "identifier").values(
                "identifier",
                "title",
                "thesis",
                "source_url",
                "published_at",
                "source_updated_at",
                "subject_code",
                "approved",
                "approval_reference",
                "related_decisions",
            )[:5]
        ),
    }
