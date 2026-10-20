from django.db import migrations


def add_stj(apps, schema_editor):
    apps.get_model("accounts", "Court").objects.using(schema_editor.connection.alias).get_or_create(
        code="STJ", defaults={"name": "Superior Tribunal de Justiça"}
    )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_protect_support")]
    operations = [migrations.RunPython(add_stj, migrations.RunPython.noop)]
