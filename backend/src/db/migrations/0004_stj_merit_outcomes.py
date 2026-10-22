from django.db import migrations

STJ_CODES = {
    237: "granted",
    972: "granted",
    239: "denied",
    238: "partial",
    235: "not_admitted",
    240: "partial_knowledge",
    241: "partial_knowledge",
    242: "partial_knowledge",
    12434: "granted",
    12435: "denied",
    12436: "not_admitted",
    12438: "partial",
    12439: "partial_knowledge",
    12440: "partial_knowledge",
    12443: "partial_knowledge",
}


def reclassify_stj(apps, schema_editor):
    FactProcess = apps.get_model("warehouse", "FactProcess")
    DimResult = apps.get_model("warehouse", "DimResult")
    result_ids = {
        name: DimResult.objects.get_or_create(name=name)[0].pk
        for name in set(STJ_CODES.values()) | {"unknown", "outside_degree"}
    }
    batch = []
    rows = (
        FactProcess.objects.filter(court="STJ")
        .select_related("degree_dimension")
        .prefetch_related("movements")
        .iterator(chunk_size=200)
    )
    for process in rows:
        if process.degree_dimension.code != "SUP":
            outcome = "outside_degree"
        else:
            evidence = [
                movement
                for movement in process.movements.all()
                if movement.code in STJ_CODES and movement.occurred_at is not None
            ]
            latest = max(evidence, key=lambda movement: (movement.occurred_at, movement.pk), default=None)
            outcome = STJ_CODES[latest.code] if latest else "unknown"
        process.result_id = result_ids[outcome]
        batch.append(process)
        if len(batch) >= 200:
            FactProcess.objects.bulk_update(batch, ["result"])
            batch.clear()
    if batch:
        FactProcess.objects.bulk_update(batch, ["result"])


class Migration(migrations.Migration):
    dependencies = [("warehouse", "0003_precedent_alignment")]
    operations = [migrations.RunPython(reclassify_stj, migrations.RunPython.noop)]
