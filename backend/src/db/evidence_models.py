"""Append-only NLP provenance. These rows never increase analytical fact counts."""
import uuid

from django.conf import settings
from django.db import models


class HistoryRow(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class NlpDocument(HistoryRow):
    source_key = models.CharField(max_length=300, unique=True)
    court = models.CharField(max_length=16)


class NlpTextVersion(HistoryRow):
    document = models.ForeignKey(NlpDocument, on_delete=models.PROTECT)
    fingerprint = models.CharField(max_length=64)
    text = models.TextField()
    sha256 = models.CharField(max_length=64)
    source = models.JSONField()
    representation = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['document', 'fingerprint'], name='nlp_text_identity')]


class NlpSourceObservation(HistoryRow):
    document = models.ForeignKey(NlpDocument, on_delete=models.PROTECT)
    sequence = models.PositiveIntegerField()
    state = models.CharField(max_length=32)
    source_url = models.URLField(max_length=2000, blank=True)
    details = models.JSONField(default=dict)
    text_version = models.ForeignKey(NlpTextVersion, null=True, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['document', 'sequence'], name='nlp_observation_order')]


class NlpExtraction(HistoryRow):
    document = models.ForeignKey(NlpDocument, on_delete=models.PROTECT)
    text_version = models.ForeignKey(NlpTextVersion, null=True, on_delete=models.PROTECT)
    observation = models.ForeignKey(NlpSourceObservation, on_delete=models.PROTECT)
    request_key = models.UUIDField(unique=True)
    result_sha256 = models.CharField(max_length=64)
    original_result = models.JSONField()
    status = models.CharField(max_length=24)
    previous = models.ForeignKey('self', null=True, on_delete=models.PROTECT)
    reason = models.TextField(blank=True)


class NlpEvidence(HistoryRow):
    extraction = models.ForeignKey(NlpExtraction, on_delete=models.PROTECT, related_name='evidences')
    annotation_id = models.CharField(max_length=128)
    original = models.JSONField()
    sha256 = models.CharField(max_length=64)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['extraction', 'annotation_id'], name='nlp_annotation_identity')]


class NlpRevision(HistoryRow):
    evidence = models.ForeignKey(NlpEvidence, on_delete=models.PROTECT, related_name='revisions')
    number = models.PositiveIntegerField()
    action = models.CharField(max_length=16)
    state = models.CharField(max_length=16)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.TextField()
    before = models.JSONField()
    after = models.JSONField()
    request_key = models.UUIDField()
    request_sha256 = models.CharField(max_length=64)
    contract_version = models.CharField(max_length=32, default='review/1.0')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['evidence', 'number'], name='nlp_revision_sequence'),
            models.UniqueConstraint(fields=['evidence', 'request_key'], name='nlp_review_idempotency'),
            models.CheckConstraint(condition=models.Q(number__gt=0), name='nlp_positive_revision'),
            models.CheckConstraint(condition=models.Q(action__in=['approve', 'correct', 'reject', 'reopen']), name='nlp_review_action'),
            models.CheckConstraint(condition=models.Q(state__in=['pending', 'approved', 'corrected', 'rejected']), name='nlp_review_state'),
        ]


class NlpSnapshot(HistoryRow):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    payload = models.JSONField()
    sha256 = models.CharField(max_length=64)
