"""Migrate and validate the dedicated synthetic production database."""

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder

from src.db.management.commands.provision_synthetic_preview import seed, verify
from src.db.sampling_models import CivilSamplingCohort

COHORT = "civil-synthetic-production"
PREFIX = "synthetic-production:"
LOGIN = "demo-production@example.test"


class Command(BaseCommand):
    help = "Provision the isolated production demonstration."

    def handle(self, **options):
        if (
            not getattr(settings, "PRODUCTION_DEMO", False)
            or settings.RESEARCH_CIVIL_COHORT != COHORT
            or connection.settings_dict["NAME"] != "datumlex_release_synthetic"
        ):
            raise CommandError("A carga sintética exige a configuração de demonstração de produção.")
        if connection.pg_version // 10000 != 18:
            raise CommandError("A demonstração exige PostgreSQL 18.")
        call_command("migrate", interactive=False, verbosity=0)
        count = len(MigrationRecorder(connection).applied_migrations())
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(4407)")
            cohort = CivilSamplingCohort.objects.filter(name=COHORT).first()
            if cohort is None:
                seed(cohort_name=COHORT, prefix=PREFIX, login=LOGIN)
                cohort = CivilSamplingCohort.objects.get(name=COHORT)
            proof = verify("default", prefix=PREFIX, login=LOGIN)
            cohort.definition["rehearsal"] = {"postgres_major": 18, "migrations": count, **proof}
            cohort.save(update_fields=["definition"])
        self.stdout.write(f"Demonstração sintética validada. Migrações: {count}.")
