"""Dimensional reference implemented at DataJud document grain, not appeal grain."""

from django.db import models


class DimTime(models.Model):
    date = models.DateField(unique=True)
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()
    day = models.PositiveSmallIntegerField()
    quarter = models.PositiveSmallIntegerField()

    class Meta:
        db_table = "dim_time"


class DimClass(models.Model):
    code = models.PositiveIntegerField(primary_key=True)
    name = models.CharField(max_length=255)

    class Meta:
        db_table = "dim_class"


class DimOrg(models.Model):
    court = models.CharField(max_length=16)
    code = models.PositiveIntegerField()
    name = models.CharField(max_length=255)
    municipality_code = models.CharField(max_length=16, blank=True)

    class Meta:
        db_table = "dim_org"
        constraints = [models.UniqueConstraint(fields=["court", "code"], name="unique_court_org")]


class DimSubject(models.Model):
    code = models.PositiveIntegerField(primary_key=True)
    name = models.CharField(max_length=255)

    class Meta:
        db_table = "dim_subject"


class ExtractionRun(models.Model):
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)
    status = models.CharField(max_length=24, default="running")
    scope = models.JSONField()
    cursor = models.JSONField(null=True)
    pages = models.PositiveIntegerField(default=0)
    fetched = models.PositiveIntegerField(default=0)
    created = models.PositiveIntegerField(default=0)
    updated = models.PositiveIntegerField(default=0)
    rejected = models.PositiveIntegerField(default=0)
    stale = models.PositiveIntegerField(default=0)
    source_total = models.PositiveBigIntegerField(null=True)
    source_total_relation = models.CharField(max_length=8, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        db_table = "extraction_run"


class FactProcess(models.Model):
    source_id = models.CharField(max_length=255, unique=True)
    number_process = models.CharField(max_length=32)
    court = models.CharField(max_length=16, default="TJDFT")
    degree = models.CharField(max_length=16)
    secrecy_level = models.PositiveSmallIntegerField(default=0)
    time = models.ForeignKey(DimTime, on_delete=models.PROTECT)
    process_class = models.ForeignKey(DimClass, on_delete=models.PROTECT)
    organization = models.ForeignKey(DimOrg, on_delete=models.PROTECT)
    subjects = models.ManyToManyField(DimSubject, through="FactProcessSubject")
    quant_process = models.PositiveSmallIntegerField(default=1)
    source_updated_at = models.DateTimeField(null=True)
    source_timestamp = models.DateTimeField(null=True)
    collected_at = models.DateTimeField(auto_now=True)
    last_run = models.ForeignKey(ExtractionRun, on_delete=models.PROTECT)
    raw_payload = models.JSONField()
    payload_hash = models.CharField(max_length=64)

    class Meta:
        db_table = "fact_process"
        indexes = [models.Index(fields=["court", "degree", "time"])]
        constraints = [models.CheckConstraint(condition=models.Q(quant_process=1), name="process_weight_one")]


class FactProcessSubject(models.Model):
    process = models.ForeignKey(FactProcess, on_delete=models.CASCADE)
    subject = models.ForeignKey(DimSubject, on_delete=models.PROTECT)

    class Meta:
        db_table = "fact_process_subject"
        constraints = [models.UniqueConstraint(fields=["process", "subject"], name="unique_process_subject")]


class ProcessMovement(models.Model):
    process = models.ForeignKey(FactProcess, on_delete=models.CASCADE, related_name="movements")
    fingerprint = models.CharField(max_length=64)
    code = models.PositiveIntegerField(null=True)
    name = models.CharField(max_length=512)
    occurred_at = models.DateTimeField(null=True)
    complements = models.JSONField(default=list)

    class Meta:
        db_table = "process_movement"
        constraints = [
            models.UniqueConstraint(fields=["process", "fingerprint"], name="unique_process_movement")
        ]


class RejectedRecord(models.Model):
    run = models.ForeignKey(ExtractionRun, on_delete=models.CASCADE)
    source_id = models.CharField(max_length=255)
    reason = models.CharField(max_length=255)

    class Meta:
        db_table = "rejected_record"
