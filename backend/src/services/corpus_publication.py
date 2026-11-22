"""Explicit, fail-closed publication permissions for legal sources."""

from uuid import UUID

from django.db.models import CharField, Q
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast

from src.db.models import LegalCorpusItem, LegalReference, NlpEvidence, NlpRevision


def reviewer(actor):
    return bool(actor.is_authenticated and actor.approved and actor.is_active and not actor.must_change_password
                and (actor.support or actor.role in ("Admin", "Master")))


def require_reviewer(actor):
    if not reviewer(actor):
        raise PermissionError("legal_review_required")


def court_items(actor, items):
    if actor.support:
        return items
    return items.filter(Q(category="doctrine") | Q(court__in=actor.courts.values("code")))


def published_references():
    return LegalReference.objects.filter(approved=True, source_metadata__permissions__display="allowed")


def published_items(use="display"):
    # The JSON authorization is a named grant. Missing values and unknown review states never grant access.
    permitted = LegalCorpusItem.objects.filter(review_status="approved", provenance__permissions__display="allowed")
    if use == "nlp":
        permitted = permitted.filter(provenance__permissions__nlp="allowed")
    elif use == "gemini":
        permitted = permitted.filter(provenance__permissions__gemini="allowed")
    elif use != "display":
        raise ValueError("unknown_publication_use")
    approved_refs = published_references().annotate(key=Cast("pk", CharField())).values("key")
    return permitted.annotate(source_reference=KeyTextTransform("reference_id", "provenance")).filter(
        ~Q(provenance__has_key="reference_id") | Q(source_reference__in=approved_refs)
    )


def allowed_versions(*, use="nlp", ids=None):
    items = published_items("nlp").filter(provenance__has_keys=("text_version", "sha256"))
    if use == "gemini":
        items = items.filter(provenance__permissions__gemini="allowed")
    if ids is not None:
        items = items.filter(provenance__text_version__in=[str(value) for value in ids])
    allowed = {}
    for version, sha256 in items.values_list("provenance__text_version", "provenance__sha256"):
        try:
            key = UUID(version)
        except (ValueError, TypeError, AttributeError):
            continue
        if isinstance(sha256, str):
            allowed.setdefault(key, set()).add(sha256)
    return allowed


def version_available(version, allowed):
    if version is None or version.sha256 not in allowed.get(version.pk, ()):
        return False
    current = version.document.nlpsourceobservation_set.order_by("-sequence").first()
    return bool(current and current.state == "available" and current.text_version_id == version.pk)


def current_evidence(items, *, use="nlp"):
    """Return IDs whose source version and frozen review still have the requested grants."""
    ids = [item["id"] for item in items]
    rows = NlpEvidence.objects.filter(pk__in=ids).select_related("extraction__text_version__document")
    allowed = allowed_versions(use=use, ids={item["text_version_id"] for item in items})
    revisions = NlpRevision.objects.filter(evidence_id__in=ids).order_by("evidence_id", "number")
    latest = {str(evidence): (number, state) for evidence, number, state in revisions.values_list(
        "evidence_id", "number", "state",
    )}
    verified = {}
    availability = {}
    requested = {item["id"]: item for item in items}
    for row in rows:
        version = row.extraction.text_version
        item = requested[str(row.pk)]
        if (latest.get(item["id"]) != (item["revision"], "approved") or item["review_status"] != "approved"
                or version is None or str(version.pk) != item["text_version_id"] or version.sha256 != item["text_sha256"]):
            continue
        if version.pk not in availability:
            availability[version.pk] = version_available(version, allowed)
        if availability[version.pk]:
            verified[item["id"]] = row
    return verified
