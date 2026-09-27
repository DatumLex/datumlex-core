import os

from django.db import transaction

from .models import AuditEvent, Court, SupportIdentity, User


@transaction.atomic
def provision_support(password=None):
    Court.objects.get_or_create(
        code="TJDFT", defaults={"name": "Tribunal de Justiça do Distrito Federal e dos Territórios"}
    )
    user = User.objects.filter(username="suport").first()
    if user:
        return user
    secret = password or os.environ.get("DATUMLEX_SUPPORT_PASSWORD")
    if not secret:
        raise ValueError("Configure DATUMLEX_SUPPORT_PASSWORD antes de implantar.")
    user = User(username="suport", name="Suporte DatumLex", role="Master", approved=True, support=True)
    user.set_password(secret)
    user.save()
    SupportIdentity.objects.create(user=user)
    AuditEvent.objects.create(
        actor=user, actor_name=user.name, action="support.provisioned", target_id=user.pk
    )
    return user


def provision_after_migrate(sender, **kwargs):
    # Test databases need no deployment credential. Deployment requires the env var.
    if os.environ.get("DATUMLEX_SUPPORT_PASSWORD"):
        provision_support()
