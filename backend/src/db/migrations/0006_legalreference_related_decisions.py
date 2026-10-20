from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("warehouse", "0005_merge_stj_provenance_and_alignment")]

    operations = [
        migrations.AddField(
            model_name="legalreference",
            name="related_decisions",
            field=models.JSONField(default=list),
        ),
    ]
