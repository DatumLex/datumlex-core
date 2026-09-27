from django.apps import AppConfig
from django.db.models.signals import post_migrate


class AccountsConfig(AppConfig):
    name = "src.accounts"

    def ready(self):
        from .provisioning import provision_after_migrate

        post_migrate.connect(provision_after_migrate, sender=self, dispatch_uid="accounts.support")
