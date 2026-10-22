import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("warehouse", "0002_resource_schema")]

    operations = [
        migrations.CreateModel(
            name="LegalReference",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("reference_type", models.CharField(choices=[("precedent", "Precedente"), ("doctrine", "Doutrina")], max_length=16)),
                ("source_institution", models.CharField(choices=[("STJ", "STJ"), ("BDJur", "BDJur")], max_length=12)),
                ("identifier", models.CharField(max_length=200)),
                ("title", models.CharField(max_length=500)),
                ("thesis", models.TextField()),
                ("authority", models.CharField(blank=True, max_length=100)),
                ("subject_code", models.PositiveIntegerField(null=True)),
                ("source_name", models.CharField(max_length=200)),
                ("source_url", models.URLField(max_length=1000)),
                ("source_locator", models.CharField(blank=True, max_length=300)),
                ("published_at", models.DateField(null=True)),
                ("approval_reference", models.CharField(max_length=200)),
                ("approved", models.BooleanField(default=False)),
                ("imported_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "legal_reference"},
        ),
        migrations.CreateModel(
            name="DecisionAssessment",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("relation", models.CharField(choices=[("aligned", "Aderente"), ("divergent", "Possível divergência"), ("distinguished", "Distinguishing justificado"), ("uncertain", "Inconclusivo")], max_length=16)),
                ("review_state", models.CharField(choices=[("pending", "Pendente"), ("reviewed", "Revisado"), ("approved", "Validado")], default="pending", max_length=16)),
                ("decision_date", models.DateField()),
                ("rationale", models.TextField()),
                ("evidence_excerpt", models.TextField(blank=True)),
                ("evidence_locator", models.CharField(blank=True, max_length=300)),
                ("reviewer", models.CharField(blank=True, max_length=200)),
                ("reviewed_at", models.DateTimeField(null=True)),
                ("approval_reference", models.CharField(blank=True, max_length=200)),
                ("imported_at", models.DateTimeField(auto_now_add=True)),
                ("local_decision", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="precedent_assessments", to="warehouse.factprocess")),
                ("reference", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="assessments", to="warehouse.legalreference")),
            ],
            options={"db_table": "decision_assessment"},
        ),
        migrations.AddConstraint(model_name="legalreference", constraint=models.UniqueConstraint(fields=("source_name", "identifier"), name="unique_legal_reference")),
        migrations.AddIndex(model_name="legalreference", index=models.Index(fields=["reference_type", "approved", "subject_code"], name="legal_ref_type_approved_idx")),
        migrations.AddConstraint(model_name="decisionassessment", constraint=models.UniqueConstraint(fields=("local_decision", "reference"), name="unique_decision_reference_assessment")),
        migrations.AddIndex(model_name="decisionassessment", index=models.Index(fields=["decision_date", "review_state", "relation"], name="decision_dt_review_rel_idx")),
    ]
