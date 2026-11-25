from django.db import models


class CivilSamplingCohort(models.Model):
    name = models.SlugField(max_length=64, unique=True)
    definition = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)


class CivilSampleMember(models.Model):
    cohort = models.ForeignKey(CivilSamplingCohort, on_delete=models.PROTECT)
    fact = models.ForeignKey("warehouse.FactProcess", on_delete=models.PROTECT)
    process = models.ForeignKey("warehouse.DimProcess", on_delete=models.PROTECT)
    court = models.CharField(max_length=16)
    year = models.PositiveSmallIntegerField()
    filing_month = models.PositiveSmallIntegerField()
    subject_code = models.PositiveIntegerField()
    origin = models.CharField(max_length=16)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cohort", "court", "year", "process"],
                name="unique_civil_sample_case_per_cell",
            )
        ]
