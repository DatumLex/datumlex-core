"""Generate an aggregate publication receipt from a local PostgreSQL snapshot."""

import json
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from src.db.court_catalog import ACTIVE_COURTS
from src.db.sampling_models import CivilSamplingCohort
from src.services.period import today
from src.services.publication_manifest import (
    build_cohort_manifest, build_manifest, is_sha256, json_date, load_revocations, read_cell, read_cohort, verify_rollback,
)


class Command(BaseCommand):
    help = "Dry-run one cell or all cells of a civil cohort in a local read-only transaction."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--cohort", required=True)
        parser.add_argument("--court", choices=ACTIVE_COURTS)
        parser.add_argument("--year", type=int)
        parser.add_argument("--all-cells", action="store_true")
        parser.add_argument("--revocations", type=Path, help="Local JSON list of revoked 20-digit CNJs (all cells only)")
        parser.add_argument("--through", type=date.fromisoformat)
        parser.add_argument("--collection", type=Path, help="Independent local collection contract JSON")
        parser.add_argument("--previous-manifest", type=Path, help="Receipt for the snapshot being rehearsed")
        parser.add_argument("--previous-digest", help="Separately retained SHA-256 of the previous receipt")

    def handle(self, **options):
        name, court, year = options["cohort"], options["court"], options["year"]
        all_cells = options.get("all_cells", False)
        revocations_path = options.get("revocations")
        if all_cells:
            through = options["through"]
            if court or year or through is None or not date(2010, 1, 1) <= through <= today() or options["collection"]:
                raise CommandError("Use --all-cells com uma data --through válida, sem tribunal, ano ou coleção.")
        else:
            if not court or year is None or not 2010 <= year <= today().year or revocations_path:
                raise CommandError("Informe tribunal e ano válidos, ou selecione --all-cells.")
            through = options["through"] or min(date(year, 12, 31), today())
            if through.year != year or through > today():
                raise CommandError("A data de corte deve estar no ano selecionado e não pode ser futura.")
        try:
            revoked = load_revocations(revocations_path)
        except (OSError, ValueError):
            raise CommandError("Lista local de revogações inválida.") from None

        previous_path, previous_digest = options["previous_manifest"], options["previous_digest"]
        if bool(previous_path) != bool(previous_digest):
            raise CommandError("Para validar rollback, forneça o manifesto anterior e seu hash independente.")
        if previous_path and not is_sha256(previous_digest):
            raise CommandError("Hash SHA-256 anterior inválido.")
        collection = self.read_json(options["collection"]) if options["collection"] else None
        previous = self.read_json(previous_path) if previous_path else None
        db = connections["default"]
        if db.vendor != "postgresql" or db.settings_dict["HOST"] not in ("", "localhost", "127.0.0.1", "::1"):
            raise CommandError("Use uma conexão PostgreSQL no computador local.")
        if db.in_atomic_block or not db.get_autocommit():
            raise CommandError("O dry-run exige uma transação independente.")

        try:
            with transaction.atomic(durable=True):
                with db.cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                    cursor.execute("SET LOCAL statement_timeout = '10s'")
                    cursor.execute("SET LOCAL lock_timeout = '1s'")
                    cursor.execute("SHOW transaction_read_only")
                    if cursor.fetchone() != ("on",):
                        raise CommandError("O PostgreSQL não confirmou a transação somente leitura.")
                if all_cells:
                    definition, tables, movements = read_cohort(name)
                    receipt, _ = build_cohort_manifest(name, through, definition, tables, movements, revoked)
                else:
                    definition, tables, movements = read_cell(name, court, year)
                    receipt = build_manifest(name, court, year, definition, tables, movements, collection, through=through)
        except CivilSamplingCohort.DoesNotExist:
            raise CommandError("Coorte não encontrada.") from None
        except ValueError:
            raise CommandError("Definição da coorte, TPU ou coleção inválida.") from None

        receipt["execution"] = {"transaction_read_only": True, "isolation": "repeatable_read"}
        if previous_path:
            receipt["rollback"] = {"verified": verify_rollback(receipt, previous, previous_digest),
                                   "previous_manifest_sha256": previous_digest}
        self.stdout.write(json.dumps(receipt, default=json_date, ensure_ascii=False, sort_keys=True, indent=2))
        if receipt["manifest"]["validation"]["status"] == "failed":
            raise CommandError("Validação falhou. Consulte os resultados agregados do manifesto.")
        if previous_path and not receipt["rollback"]["verified"]:
            raise CommandError("A fotografia da simulação não confere com o manifesto anterior.")

    @staticmethod
    def read_json(path):
        try:
            with path.open(encoding="utf-8") as source:
                return json.load(source)
        except (OSError, ValueError):
            raise CommandError("Não foi possível ler o JSON informado.") from None
