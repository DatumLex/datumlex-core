from django.db import transaction

from src.db.models import (
    DimClass,
    DimOrg,
    DimSubject,
    DimTime,
    FactProcess,
    FactProcessSubject,
    ProcessMovement,
)


@transaction.atomic
def load_record(record, run):
    existing = FactProcess.objects.filter(source_id=record["source_id"]).first()
    if (
        existing
        and existing.source_updated_at
        and (record["source_updated_at"] is None or record["source_updated_at"] < existing.source_updated_at)
    ):
        return "stale"
    day = record["filing"]
    time, _ = DimTime.objects.get_or_create(
        date=day,
        defaults={
            "year": day.year,
            "month": day.month,
            "day": day.day,
            "quarter": (day.month - 1) // 3 + 1,
        },
    )
    process_class, _ = DimClass.objects.update_or_create(
        code=record["class_code"], defaults={"name": record["class_name"]}
    )
    org, _ = DimOrg.objects.update_or_create(
        court="TJDFT",
        code=record["org_code"],
        defaults={
            "name": record["org_name"],
            "municipality_code": record["municipality_code"],
        },
    )
    process, created = FactProcess.objects.update_or_create(
        source_id=record["source_id"],
        defaults={
            "number_process": record["number_process"],
            "degree": record["degree"],
            "court": "TJDFT",
            "time": time,
            "process_class": process_class,
            "organization": org,
            "last_run": run,
            "source_updated_at": record["source_updated_at"],
            "source_timestamp": record["source_timestamp"],
            "raw_payload": record["raw"],
            "payload_hash": record["payload_hash"],
        },
    )
    FactProcessSubject.objects.filter(process=process).exclude(subject_id__in=record["subjects"]).delete()
    for code, name in record["subjects"].items():
        subject, _ = DimSubject.objects.update_or_create(code=code, defaults={"name": name})
        FactProcessSubject.objects.get_or_create(process=process, subject=subject)
    # Movements are a source snapshot; a later source revision replaces removed events.
    process.movements.all().delete()
    ProcessMovement.objects.bulk_create(
        [
            ProcessMovement(process=process, fingerprint=fingerprint, **values)
            for fingerprint, values in record["movements"].items()
        ]
    )
    return "created" if created else "updated"
