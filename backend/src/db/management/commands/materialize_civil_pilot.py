"""Copy a validated civil projection between two isolated local PostgreSQL databases."""

import json
import re
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from src.accounts.models import Court
from src.db.models import DimResult, DimSubject, FactProcess, FactProcessSubject, ProcessMovement
from src.db.sampling_models import CivilSampleMember, CivilSamplingCohort
from src.services.publication_manifest import (
    FACT_DEPENDENCIES, build_cohort_manifest, build_manifest, digest, is_sha256, load_revocations,
    read_cell, read_cohort, validate_cell, verify_rollback,
)

MODELS = (Court, *FACT_DEPENDENCIES.values(), DimSubject, CivilSamplingCohort,
          FactProcess, FactProcessSubject, CivilSampleMember, ProcessMovement)
LOCAL_HOSTS = ("", "localhost", "127.0.0.1", "::1")
RESULT_SEEDS = {"denied", "unknown", "partial_knowledge", "not_admitted", "partial", "granted", "outside_degree"}


def insert_rows(db, cursor, model, rows):
    if not rows:
        return 0
    fields = model._meta.concrete_fields
    quote = db.ops.quote_name
    table = quote(model._meta.db_table)
    columns = ", ".join(quote(field.column) for field in fields)
    params = ", ".join("%s" for _ in fields)
    statement = (f"INSERT INTO {table} ({columns}) VALUES ({params}) "
                 f"ON CONFLICT ({quote(model._meta.pk.column)}) DO NOTHING")
    payload = [tuple(field.get_db_prep_save(row[field.attname], db) for field in fields) for row in rows]
    cursor.executemany(statement, payload)
    inserted = cursor.rowcount
    if inserted and model._meta.pk.get_internal_type() in ("AutoField", "BigAutoField", "SmallAutoField"):
        cursor.execute("SELECT pg_get_serial_sequence(%s, %s)", (model._meta.db_table, model._meta.pk.column))
        sequence = cursor.fetchone()[0]
        cursor.execute(f"SELECT MAX({quote(model._meta.pk.column)}) FROM {table}")
        restart = cursor.fetchone()[0] + 1
        # Transactional sequence restart. Identifiers originate from Django model metadata and pg_catalog.
        identifier = ".".join(quote(part) for part in sequence.split("."))
        cursor.execute(f"ALTER SEQUENCE {identifier} RESTART WITH {int(restart)}")
    return inserted


class Command(BaseCommand):
    help = "Materialize one pinned snapshot for development. Does not approve or publish a batch."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--source", default="default")
        parser.add_argument("--destination", required=True)
        parser.add_argument("--manifest", required=True, type=Path)
        parser.add_argument("--manifest-sha256", required=True)
        parser.add_argument("--collection", type=Path)
        parser.add_argument("--revocations", type=Path)

    def handle(self, **options):
        source, target = options["source"], options["destination"]
        if source not in connections or target not in connections:
            raise CommandError("Aliases PostgreSQL locais inválidos.")
        databases = [connections[alias] for alias in (source, target)]
        names = [db.settings_dict["NAME"] for db in databases]
        if (source == target or names[0] == names[1] or not re.fullmatch(r"datumlex_ops_[a-z0-9_]+", names[1])
                or any(db.vendor != "postgresql" or db.settings_dict["HOST"] not in LOCAL_HOSTS for db in databases)):
            raise CommandError("Origem e destino devem ser PostgreSQL locais distintos, com destino datumlex_ops_*.")
        try:
            expected = json.loads(options["manifest"].read_text(encoding="utf-8"))
            body = expected["manifest"]
            scope = body["scope"]
            all_cells = scope.get("kind") == "cohort"
            through = date.fromisoformat(scope["end"])
            expected_sha = options["manifest_sha256"]
            if (not is_sha256(expected_sha) or expected_sha != expected["sha256"] or expected_sha != digest(body)
                    or body["mode"] != "dry_run" or body["publication"]["status"] != "blocked"
                    or body["validation"]["status"] != "passed"):
                raise ValueError
            if all_cells:
                if options["collection"] or body["collection"] is not None:
                    raise ValueError
                revoked = load_revocations(options["revocations"])
            else:
                if not options["collection"] or options["revocations"] or body["collection"]["synthetic"] is not True:
                    raise ValueError
                collection = json.loads(options["collection"].read_text(encoding="utf-8"))
                args = (scope["cohort"], scope["court"], scope["year"])
        except (OSError, ValueError, KeyError, TypeError):
            raise CommandError("Recibo válido do dry-run e SHA-256 independente são obrigatórios.") from None

        def read_projection(alias):
            if all_cells:
                definition, rows, movements = read_cohort(scope["cohort"], using=alias)
                receipt, proofs = build_cohort_manifest(scope["cohort"], through, definition, rows, movements, revoked)
            else:
                definition, rows, movements = read_cell(*args, using=alias)
                receipt = build_manifest(*args, definition, rows, movements, collection, through=through)
                proofs = validate_cell(rows, movements, scope["court"], date.fromisoformat(scope["start"]),
                                       through, set(definition["subjects"]))["proofs"]
            return receipt, rows, proofs

        with transaction.atomic(using=source, durable=True), databases[0].cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '10s'")
            cursor.execute("SET LOCAL lock_timeout = '1s'")
            cursor.execute("SELECT current_database(), current_setting('transaction_read_only')")
            if cursor.fetchone() != (names[0], "on"):
                raise CommandError("A origem não confirmou a identidade ou leitura exclusiva.")
            source_receipt, tables, evidence = read_projection(source)
            if source_receipt["sha256"] != expected_sha:
                raise CommandError("A seleção da origem não confere com o manifesto fixado. Nenhum dado copiado.")

        tables["process_movement"] = {
            proof["movement_id"]: {"id": proof["movement_id"], "process_id": fact_id, "code": proof["code"],
                                   "occurred_at": proof["date"], "fingerprint": proof["fingerprint"],
                                   "name": "", "complements": []}
            for fact_id, proof in evidence.items()
        }
        tables["fact_resource"] = {key: {**row, "raw_payload": {}} for key, row in tables["fact_resource"].items()}
        tables["extraction_run"] = {key: {**row, "cursor": None, "error": ""} for key, row in tables["extraction_run"].items()}

        db = databases[1]
        with transaction.atomic(using=target, durable=True), db.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '1s'")
            cursor.execute("SET LOCAL statement_timeout = '10s'")
            cursor.execute("SELECT current_database()")
            if cursor.fetchone() != (names[1],):
                raise CommandError("Identidade do destino divergente.")
            cursor.execute("SELECT pg_try_advisory_xact_lock(24102310431)")
            if not cursor.fetchone()[0]:
                raise CommandError("Já existe uma materialização em curso.")
            locked_tables = ", ".join(db.ops.quote_name(model._meta.db_table) for model in MODELS)
            cursor.execute(f"LOCK TABLE {locked_tables} IN SHARE ROW EXCLUSIVE MODE")
            result_seeds = DimResult.objects.using(target)
            replaced_seeds = 0
            if (not FactProcess.objects.using(target).exists()
                    and set(result_seeds.values_list("name", flat=True)) == RESULT_SEEDS):
                # Django's seed IDs can differ from a restored database. Preserve source IDs in the pilot.
                replaced_seeds, _ = result_seeds.delete()
            inserted = {model._meta.db_table: insert_rows(db, cursor, model, tables[model._meta.db_table].values())
                        for model in MODELS}
            for model in MODELS:
                if model is not Court and model.objects.using(target).count() != len(tables[model._meta.db_table]):
                    raise CommandError("O destino contém linhas fora da projeção aprovada para o piloto.")
            if (FactProcess.objects.using(target).exclude(raw_payload={}).exists()
                    or ProcessMovement.objects.using(target).exclude(complements=[]).exists()):
                raise CommandError("O destino contém dados brutos fora do perfil seletivo.")
            target_receipt, _, _ = read_projection(target)
            if not verify_rollback(target_receipt, expected, expected_sha):
                raise CommandError("O destino não reproduziu a fotografia seletiva. Alterações revertidas.")
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

        self.stdout.write(json.dumps({
            "database": names[1], "inserted": inserted, "source_sha256": expected_sha,
            "snapshot_sha256": target_receipt["manifest"]["snapshot"]["sha256"],
            "publication_status": "blocked", "source_read_only": True, "replaced_result_seed_rows": replaced_seeds,
        }, sort_keys=True))
