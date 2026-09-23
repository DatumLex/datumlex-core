from django.db import transaction

from src.db.models import (
    DimClass,
    DimDegree,
    DimOrg,
    DimProcess,
    DimResult,
    DimSubject,
    DimTime,
    FactProcess,
    FactProcessSubject,
    ProcessMovement,
)
from src.services.outcomes import classify


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
        code=record["class_code"], defaults={"name": record["class_name"][:100]}
    )
    org, _ = DimOrg.objects.update_or_create(
        court="TJDFT",
        code=record["org_code"],
        defaults={
            "name": record["org_name"][:100],
            "municipality_code": record["municipality_code"],
        },
    )
    process_dimension, _ = DimProcess.objects.get_or_create(number_process=record["number_process"])
    degree, _ = DimDegree.objects.get_or_create(code=record["degree"], defaults={"name": record["degree"]})
    unknown, _ = DimResult.objects.get_or_create(name="unknown")
    process, created = FactProcess.objects.update_or_create(
        source_id=record["source_id"],
        defaults={
            "process_dimension": process_dimension,
            "degree_dimension": degree,
            "result": unknown,
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
    FactProcessSubject.objects.filter(process=process).exclude(subject__code__in=record["subjects"]).delete()
    for code, name in record["subjects"].items():
        subject, _ = DimSubject.objects.update_or_create(code=code, defaults={"name": name[:100]})
        FactProcessSubject.objects.get_or_create(process=process, subject=subject)
    # Movements are a source snapshot; a later source revision replaces removed events.
    process.movements.all().delete()
    ProcessMovement.objects.bulk_create(
        [
            ProcessMovement(process=process, fingerprint=fingerprint, **values)
            for fingerprint, values in record["movements"].items()
        ]
    )
    outcome = classify(process)["outcome"]
    # Fit the reference's varchar(20); API retains its established exclusion label.
    result_name = "outside_degree" if outcome == "outside_appellate_degree" else outcome
    process.result, _ = DimResult.objects.get_or_create(name=result_name)
    process.save(update_fields=["result"])
    return "created" if created else "updated"
