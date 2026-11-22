"""Provision and rehearse restoration on the dedicated Railway 4F database."""

from copy import deepcopy
from datetime import date
from hashlib import sha256
from io import StringIO
from os import environ
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import psycopg
from psycopg import sql

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, connections, transaction
from django.db.migrations.recorder import MigrationRecorder

from src.accounts.models import AuditEvent, Court, SupportIdentity, User
from src.db.models import ExtractionRun, FactProcess, LegalCorpusItem, LegalReference
from src.db.sampling_models import CivilSampleMember, CivilSamplingCohort
from src.etl.loader import load_record
from src.etl.transformer import normalize
from src.services.corpus_publication import published_items
from src.services.statistics_service import metrics

COHORT = "civil-synthetic-4f"
PREFIX = "synthetic-4f:"
LOGIN = "demo-4f@example.test"
NUMBER = "00000000000000000001"
DB = "datumlex_preview_4f_synthetic"
RESTORE = DB + "_restore"
SCOPE = {"court": "TJDFT", "subject_codes": [10433], "start": "2023-01-01",
         "end": "2023-12-31", "end_exclusive": "2024-01-01", "origin": PREFIX}


def seed():
    secret = environ.get("DATUMLEX_DEMO_PASSWORD", "")
    if len(secret) < 32 or FactProcess.objects.exists() or LegalCorpusItem.objects.exists() or LegalReference.objects.exists():
        raise CommandError("A primeira carga exige banco dedicado vazio e credencial sintética.")
    with transaction.atomic():
        # The first Railway attempt ran the old migration hook on this newly created database.
        # Remove only that confirmed migration artifact before seeding the sole demo reader.
        if User.objects.exists():
            legacy = User.objects.filter(username="suport", role="Master", support=True, email__isnull=True,
                                         cpf__isnull=True, last_login__isnull=True).first()
            if (not legacy or User.objects.count() != 1 or Session.objects.exists()
                    or list(AuditEvent.objects.values_list("actor_id", "action")) != [(legacy.pk, "support.provisioned")]
                    or not SupportIdentity.objects.filter(user=legacy).exists()):
                raise CommandError("O banco dedicado contém uma conta fora do provisionamento inicial.")
            AuditEvent.objects.filter(actor=legacy, action="support.provisioned").delete()
            SupportIdentity.objects.filter(user=legacy).delete()
            legacy.delete()
        run = ExtractionRun.objects.create(scope=SCOPE)
        raw = {"_id": PREFIX + "case", "_source": {
            "tribunal": "TJDFT", "numeroProcesso": NUMBER, "nivelSigilo": 0, "grau": "G2",
            "dataAjuizamento": "2023-03-30T10:00:00Z",
            "dataHoraUltimaAtualizacao": "2023-06-01T10:00:00Z",
            "classe": {"codigo": 198, "nome": "Apelação Cível de demonstração"},
            "orgaoJulgador": {"codigo": 42, "nome": "Órgão fictício"},
            "assuntos": [{"codigo": 10433, "nome": "Indenização por Dano Moral"}],
            "movimentos": [{"codigo": 237, "nome": "Provimento sintético", "dataHora": "2023-06-01T10:00:00Z"}],
        }}
        record = normalize(raw, SCOPE)
        record["raw"] = {"synthetic": True}
        load_record(record, run)
        fact = FactProcess.objects.get()
        cohort = CivilSamplingCohort.objects.create(name=COHORT, definition={"target": 325, "start_year": 2010})
        CivilSampleMember.objects.create(cohort=cohort, fact=fact, process=fact.process_dimension,
                                        court="TJDFT", year=2023, filing_month=3, subject_code=10433, origin="synthetic")
        court, _ = Court.objects.get_or_create(code="TJDFT", defaults={"name": "TJDFT"})
        reader = User.objects.create_user(username="synthetic-reader-4f", name="Leitor de demonstração",
                                          email=LOGIN, password=secret, approved=True)
        reader.courts.add(court)
        for approved in (True, False):
            label = "Precedente sintético de demonstração" if approved else "Referência sintética pendente"
            identifier = PREFIX + ("precedent" if approved else "pending")
            grant = {"display": "allowed"} if approved else {}
            url = "https://example.org/"
            ref = LegalReference.objects.create(
                source_name="Acervo fictício", identifier=identifier, reference_type="precedent",
                source_institution="TJDFT", title=label, source_url=url, approved=approved,
                source_metadata={"synthetic": True, "permissions": grant},
            )
            item = LegalCorpusItem.objects.create(
                origin_key=f"reference:{ref.pk}", title=label, category="precedent", court="TJDFT",
                date=date(2023, 6, 1), source_name="Acervo fictício", source_url=url,
                review_status="approved" if approved else "pending",
                provenance={"synthetic": True, "permissions": grant, "reference_id": ref.pk,
                            "metadata": {"id": identifier, "topics": ["dano-moral"]}},
            )
            item.topic_matches.create(topic="dano-moral")


def verify(alias):
    facts = FactProcess.objects.using(alias)
    if list(facts.values_list("source_id", "process_dimension__number_process", "raw_payload")) != [
        (PREFIX + "case", NUMBER, {"synthetic": True}),
    ]:
        raise CommandError("Conteúdo processual fora da demonstração.")
    if list(User.objects.using(alias).values_list("email", "role", "is_superuser")) != [(LOGIN, "Padrão", False)]:
        raise CommandError("Conta fora da demonstração.")
    sources = LegalCorpusItem.objects.using(alias)
    if sources.count() != 2 or sources.exclude(provenance__synthetic=True).exists():
        raise CommandError("Catálogo fora da demonstração.")
    if LegalReference.objects.using(alias).exclude(identifier__startswith=PREFIX).exists():
        raise CommandError("Referência fora da demonstração.")
    visible = published_items().using(alias).count()
    report = metrics(facts)
    if (visible != 1 or report["binary_denominator"] != 1
            or CivilSampleMember.objects.using(alias).count() != 1
            or published_items("nlp").using(alias).exists() or published_items("gemini").using(alias).exists()):
        raise CommandError("Os indicadores ou permissões da demonstração divergiram.")
    return {"facts": facts.count(), "public_sources": visible, "eligible": report["binary_denominator"]}


class Command(BaseCommand):
    help = "Provision the exclusively synthetic 4F preview on Railway."

    def handle(self, **options):
        if not settings.SYNTHETIC_PREVIEW:
            raise CommandError("Use somente o ambiente Railway de demonstração.")
        target = urlsplit(environ["DATABASE_URL"])
        admin_url = target._replace(path="/postgres").geturl()
        # Work never touches the existing database on this private PostgreSQL service.
        with psycopg.connect(admin_url, autocommit=True) as admin:
            with admin.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(4406), current_setting('server_version_num')")
                acquired, server_version = cursor.fetchone()
                if not acquired or int(server_version) // 10000 != 18:
                    raise CommandError("A demonstração exige PostgreSQL 18 e execução exclusiva.")
                cursor.execute("SELECT 1 FROM pg_database WHERE datname=%s", [DB])
                if not cursor.fetchone():
                    cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB)))
                call_command("migrate", interactive=False, verbosity=0)
                count = len(MigrationRecorder(connection).applied_migrations())
                if count != 36:
                    raise CommandError("A contagem do esquema diverge das 36 migrações esperadas.")
                cohort = CivilSamplingCohort.objects.filter(name=COHORT).first()
                if not cohort:
                    seed()
                    cohort = CivilSamplingCohort.objects.get(name=COHORT)
                baseline = verify("default")
                if cohort.definition.get("rehearsal"):
                    self.stdout.write("Demonstração sintética já provisionada e validada.")
                    return
                with transaction.atomic():
                    LegalReference.objects.filter(approved=True).update(approved=False)
                    if published_items().exists():
                        raise CommandError("A revogação de teste falhou.")
                    transaction.set_rollback(True)
                if verify("default") != baseline:
                    raise CommandError("A reversão da revogação falhou.")

                cursor.execute("SELECT 1 FROM pg_database WHERE datname=%s", [RESTORE])
                if cursor.fetchone():
                    raise CommandError("O banco de restauração já existe. Verifique seu estado antes de reutilizá-lo.")
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(RESTORE)))
                copy_alias = "preview_restore"
                connections.databases[copy_alias] = {**deepcopy(connections.databases["default"]), "NAME": RESTORE}
                try:
                    with TemporaryDirectory() as temp:
                        output = StringIO()
                        call_command("dumpdata", "--all", exclude=["contenttypes", "auth.permission"], stdout=output)
                        snapshot = output.getvalue().encode("utf-8")
                        backup = Path(temp) / "synthetic.json"
                        backup.write_bytes(snapshot)
                        call_command("migrate", database=copy_alias, interactive=False, verbosity=0)
                        call_command("loaddata", str(backup), database=copy_alias, verbosity=0)
                        if verify(copy_alias) != baseline:
                            raise CommandError("A restauração sintética divergiu da fotografia.")
                        connections[copy_alias].check_constraints()
                finally:
                    connections[copy_alias].close()
                    cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(RESTORE)))
                proof = {"postgres_major": 18, "migrations": count, "backup_sha256": sha256(snapshot).hexdigest(),
                         "backup_bytes": len(snapshot), "restored": True, "rollback_verified": True, **baseline}
                cohort.definition["rehearsal"] = proof
                cohort.save(update_fields=["definition"])
                self.stdout.write("Restauração e reversão verificadas no PostgreSQL 18 da prévia.")
