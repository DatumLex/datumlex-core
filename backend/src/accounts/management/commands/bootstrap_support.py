from django.core.management.base import BaseCommand, CommandError

from src.accounts.provisioning import provision_support


class Command(BaseCommand):
    help = "Idempotently provision suport using DATUMLEX_SUPPORT_PASSWORD; never reset an existing password."

    def handle(self, *args, **options):
        try:
            provision_support()
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS("Conta de suporte provisionada. A senha existente não foi alterada.")
        )
