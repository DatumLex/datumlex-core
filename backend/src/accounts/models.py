from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower


class User(AbstractUser):
    name = models.CharField(max_length=200)
    email = models.EmailField(null=True, unique=True)
    cpf = models.CharField(max_length=11, null=True, unique=True)
    role = models.CharField(
        max_length=10, default="Padrão", choices=[(r, r) for r in ("Master", "Admin", "Padrão")]
    )
    approved = models.BooleanField(default=False)
    support = models.BooleanField(default=False)
    must_change_password = models.BooleanField(default=False)
    courts = models.ManyToManyField("Court", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("email"), name="account_email_case_unique"),
            models.CheckConstraint(
                condition=models.Q(role__in=["Master", "Admin", "Padrão"]), name="account_valid_role"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(support=True, username="suport", role="Master", approved=True, is_active=True)
                    | (models.Q(support=False) & ~models.Q(username="suport"))
                ),
                name="support_identity_rules",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk, support=True).exists():
            previous = type(self).objects.get(pk=self.pk)
            if previous.password != self.password:
                raise ValidationError("A senha da conta de suporte não pode ser alterada.")
            if not (
                self.support
                and self.username == "suport"
                and self.role == "Master"
                and self.approved
                and self.is_active
            ):
                raise ValidationError("A conta de suporte é protegida.")
        self.email = self.email.strip().lower() if self.email else None
        super().save(*args, **kwargs)


class Court(models.Model):
    code = models.CharField(max_length=16, primary_key=True)
    name = models.CharField(max_length=200)


class SupportIdentity(models.Model):
    # A protected FK also prevents QuerySet.delete() from deleting this account.
    user = models.OneToOneField(User, on_delete=models.PROTECT, primary_key=True)


class AuditEvent(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    actor_name = models.CharField(max_length=200)
    action = models.CharField(max_length=80)
    target_id = models.PositiveBigIntegerField(null=True)
    details = models.JSONField(default=dict)


class RequestLimit(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField()
