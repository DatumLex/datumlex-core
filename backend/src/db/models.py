"""Dimensional reference implemented at DataJud document grain, not appeal grain."""

from django.db import models


class DimTime(models.Model):
    id = models.BigAutoField(primary_key=True, db_column="id_time")
    date = models.DateField(unique=True, db_column="data")
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()
    day = models.PositiveSmallIntegerField()
    quarter = models.PositiveSmallIntegerField()

    class Meta:
        db_table = "dim_time"


class DimClass(models.Model):
    id = models.BigAutoField(primary_key=True, db_column="id_class")
    code = models.PositiveIntegerField(unique=True, db_column="code_class")
    name = models.CharField(max_length=100, db_column="name_class")

    class Meta:
        db_table = "dim_class"


class DimOrg(models.Model):
    id = models.BigAutoField(primary_key=True, db_column="id_org")
    court = models.CharField(max_length=16)
    code = models.PositiveIntegerField(db_column="code_org")
    name = models.CharField(max_length=100, db_column="name_org")
    municipality_code = models.PositiveIntegerField(null=True, db_column="ibge_code")

    class Meta:
        db_table = "dim_org"
        constraints = [models.UniqueConstraint(fields=["court", "code"], name="unique_court_org")]


class DimSubject(models.Model):
    id = models.BigAutoField(primary_key=True, db_column="id_subject")
    code = models.PositiveIntegerField(unique=True, db_column="code_subject")
    name = models.CharField(max_length=100, db_column="name_subject")

    class Meta:
        db_table = "dim_subject"


class DimDegree(models.Model):
    id = models.BigAutoField(primary_key=True, db_column="id_degree")
    code = models.CharField(max_length=50, unique=True, db_column="code_degree")
    name = models.CharField(max_length=100, db_column="name_degree")

    class Meta:
        db_table = "dim_degree"


class DimProcess(models.Model):
    id = models.BigAutoField(primary_key=True, db_column="id_process")
    number_process = models.CharField(max_length=20, unique=True)
    secrecy_level = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "dim_process"


class DimResult(models.Model):
    id = models.BigAutoField(primary_key=True, db_column="id_result")
    name = models.CharField(max_length=20, unique=True, db_column="name_result")

    class Meta:
        db_table = "dim_result"


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
    """Fact_Resource at DataJud document grain; Python name preserves internal callers."""

    id = models.BigAutoField(primary_key=True, db_column="id_resource")
    source_id = models.CharField(max_length=255, unique=True)
    process_dimension = models.ForeignKey(DimProcess, on_delete=models.PROTECT, db_column="id_process")
    court = models.CharField(max_length=16, default="TJDFT")
    degree_dimension = models.ForeignKey(DimDegree, on_delete=models.PROTECT, db_column="id_degree")
    result = models.ForeignKey(DimResult, on_delete=models.PROTECT, db_column="id_result")
    time = models.ForeignKey(DimTime, on_delete=models.PROTECT, db_column="id_time")
    process_class = models.ForeignKey(DimClass, on_delete=models.PROTECT, db_column="id_class")
    organization = models.ForeignKey(DimOrg, on_delete=models.PROTECT, db_column="id_org")
    subjects = models.ManyToManyField(DimSubject, through="FactProcessSubject")
    quant_process = models.PositiveSmallIntegerField(default=1, db_column="quant_resource")
    source_updated_at = models.DateTimeField(null=True)
    source_timestamp = models.DateTimeField(null=True)
    collected_at = models.DateTimeField(auto_now=True)
    last_run = models.ForeignKey(ExtractionRun, on_delete=models.PROTECT)
    raw_payload = models.JSONField()
    payload_hash = models.CharField(max_length=64)

    class Meta:
        db_table = "fact_resource"
        indexes = [models.Index(fields=["court", "degree_dimension", "time"])]
        constraints = [models.CheckConstraint(condition=models.Q(quant_process=1), name="process_weight_one")]

    @property
    def number_process(self):
        return self.process_dimension.number_process

    @property
    def degree(self):
        return self.degree_dimension.code


class FactProcessSubject(models.Model):
    process = models.ForeignKey(FactProcess, on_delete=models.CASCADE, db_column="id_resource")
    subject = models.ForeignKey(DimSubject, on_delete=models.PROTECT, db_column="id_subject")

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
