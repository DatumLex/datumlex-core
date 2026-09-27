import hashlib
import json
import re
import uuid
from datetime import timedelta
from functools import wraps

from django.contrib.auth import login as session_login
from django.contrib.auth import logout as session_logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .middleware import denied
from .models import AuditEvent, Court, RequestLimit, User


def csrf_failure(request, reason=""):
    return denied("A sessão de segurança expirou. Atualize a página e tente novamente.", code="csrf_failed")


def api(methods):
    def decorate(fn):
        @require_http_methods(methods)
        @wraps(fn)
        def wrapped(request, *args, **kwargs):
            try:
                request.payload = json.loads(request.body or b"{}")
                if not isinstance(request.payload, dict):
                    raise ValueError("Envie um objeto JSON.")
                return JsonResponse(fn(request, *args, **kwargs))
            except (ValueError, ValidationError) as exc:
                message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
                return denied(message, 400, "invalid_input")
            except IntegrityError:
                return denied("CPF ou e-mail já cadastrado, ou dados incompatíveis.", 409, "conflict")
            except PermissionError as exc:
                return denied(str(exc))
            except User.DoesNotExist:
                return denied("Usuário não encontrado.", 404, "not_found")

        return wrapped

    return decorate


def text(data, key, maximum=200):
    value = data.get(key, "")
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f"Campo inválido: {key}.")
    return value.strip()


def password(data):
    value = data.get("password", "")
    if not isinstance(value, str) or len(value) > 256:
        raise ValueError("Senha inválida.")
    validate_password(value)
    return value


def identity(data):
    name, email = text(data, "name"), text(data, "email", 254).lower()
    cpf = re.sub(r"[.\-\s]", "", text(data, "cpf", 20))
    if len(name.split()) < 2:
        raise ValueError("Informe o nome completo.")
    validate_email(email)
    if not re.fullmatch(r"[0-9]{11}", cpf) or len(set(cpf)) == 1:
        raise ValueError("CPF inválido.")
    for length in (9, 10):
        digit = (sum(int(cpf[i]) * (length + 1 - i) for i in range(length)) * 10 % 11) % 10
        if digit != int(cpf[length]):
            raise ValueError("CPF inválido.")
    return {"name": name, "email": email, "cpf": cpf}


def serialize(user):
    courts = Court.objects.all() if user.support else user.courts.all()
    return {
        "id": user.pk,
        "name": user.name,
        "email": user.email or "",
        "cpf": user.cpf or "",
        "role": user.role,
        "status": "Ativo"
        if user.approved and user.is_active
        else "Pendente"
        if not user.approved
        else "Inativo",
        "courts": list(courts.order_by("code").values_list("code", flat=True)),
        "support": user.support,
        "must_change_password": user.must_change_password,
    }


def audit(request, action, target=None, details=None):
    actor = request.user if request.user.is_authenticated else None
    AuditEvent.objects.create(
        actor=actor,
        actor_name=actor.name if actor else "anonymous",
        action=action,
        target_id=target,
        details=details or {},
    )


def throttle(request, category, identifier="", maximum=10):
    now = timezone.now()
    keys = [f"{category}:ip:{request.META.get('REMOTE_ADDR', '')}"]
    if identifier:
        keys.append(f"{category}:identity:{identifier}")
    for raw in keys:
        with transaction.atomic():
            key = hashlib.sha256(raw.encode()).hexdigest()
            row, _ = RequestLimit.objects.select_for_update().get_or_create(
                key=key, defaults={"expires_at": now + timedelta(minutes=15)}
            )
            if row.expires_at <= now:
                row.count, row.expires_at = 0, now + timedelta(minutes=15)
            if row.count >= maximum:
                raise PermissionError("Muitas tentativas. Aguarde 15 minutos antes de tentar novamente.")
            row.count += 1
            row.save()


@api(["GET"])
def csrf(request):
    return {"csrfToken": get_token(request)}


@api(["POST"])
def register(request):
    throttle(request, "register", maximum=20)
    if set(request.payload) - {"name", "email", "cpf", "password"}:
        raise ValueError("O cadastro público aceita somente nome, CPF, e-mail e senha.")
    values = identity(request.payload)
    secret = password(request.payload)
    with transaction.atomic():
        user = User(username=uuid.uuid4().hex, **values)
        user.set_password(secret)
        user.save()
        audit(request, "user.registered", user.pk)
    return {"message": "Cadastro enviado. Aguarde a aprovação de um responsável."}


@api(["POST"])
def login(request):
    identifier = text(request.payload, "login", 254).lower()
    if "@" not in identifier and identifier != "suport":
        identifier = re.sub(r"[.\-\s]", "", identifier)
    throttle(request, "login", identifier, maximum=30)
    secret = request.payload.get("password", "")
    if not isinstance(secret, str) or len(secret) > 256:
        raise ValueError("Senha inválida.")
    user = (
        User.objects.filter(username="suport", support=True).first()
        if identifier == "suport"
        else User.objects.filter(Q(email=identifier) | Q(cpf=identifier), support=False).first()
    )
    # Support's stored hash is immutable too: verify without an automatic rehash setter.
    if user:
        valid = check_password(secret, user.password) if user.support else user.check_password(secret)
    else:
        make_password(secret)
        valid = False
    if not valid:
        audit(request, "login.failed")
        raise PermissionError("Login ou senha inválidos.")
    if not user.approved or not user.is_active:
        audit(request, "login.blocked", user.pk)
        raise PermissionError("Seu cadastro está pendente de aprovação ou inativo.")
    session_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    audit(request, "login.succeeded", user.pk)
    return {"user": serialize(user), "csrfToken": get_token(request)}


@api(["POST"])
def logout(request):
    audit(request, "logout", request.user.pk)
    session_logout(request)
    return {"message": "Sessão encerrada.", "csrfToken": get_token(request)}


@api(["GET"])
def me(request):
    return {
        "user": serialize(request.user),
        "courts": list(Court.objects.order_by("code").values("code", "name")),
    }


@api(["POST"])
def change_password(request):
    if request.user.support:
        raise PermissionError("A senha da conta de suporte não pode ser alterada.")
    old = request.payload.get("current_password")
    if not isinstance(old, str) or len(old) > 256 or not request.user.check_password(old):
        raise PermissionError("Senha atual inválida.")
    secret = password(request.payload)
    with transaction.atomic():
        request.user.set_password(secret)
        request.user.must_change_password = False
        request.user.save()
        audit(request, "password.changed", request.user.pk)
    update_session_auth_hash(request, request.user)
    return {"user": serialize(request.user)}


def management(request, target=None):
    if request.user.role not in {"Master", "Admin"}:
        raise PermissionError("Você não possui acesso ao gerenciamento de usuários.")
    if target and (target.support or (request.user.role == "Admin" and target.role != "Padrão")):
        raise PermissionError("Você não pode alterar este usuário.")


def apply_permissions(request, user):
    data = request.payload
    allowed = {"name", "email", "cpf", "password", "password_confirmation", "role", "status", "courts"}
    if set(data) - allowed:
        raise ValueError("Campos não permitidos no cadastro.")
    role = data.get("role", user.role)
    status = data.get("status", "Ativo" if user.approved else "Pendente")
    selected = data.get("courts", [])
    if (
        not isinstance(role, str)
        or not isinstance(status, str)
        or role not in {"Master", "Admin", "Padrão"}
        or status not in {"Ativo", "Pendente", "Inativo"}
    ):
        raise ValueError("Perfil ou status inválido.")
    if request.user.role == "Admin" and role != "Padrão":
        raise PermissionError("Admin pode gerenciar somente usuários Padrão.")
    if user.pk == request.user.pk and (role != user.role or status != "Ativo"):
        raise PermissionError("Você não pode remover seu próprio acesso.")
    if (
        not isinstance(selected, list)
        or any(not isinstance(c, str) for c in selected)
        or set(selected) - set(Court.objects.values_list("code", flat=True))
    ):
        raise ValueError("Selecione tribunais válidos.")
    user.role, user.approved, user.is_active = role, status != "Pendente", status != "Inativo"
    return selected


@api(["GET", "POST"])
def users(request):
    management(request)
    if request.method == "GET":
        query = User.objects.filter(support=False).prefetch_related("courts").order_by("name", "pk")
        search = request.GET.get("q", "").strip()
        if search:
            query = query.filter(
                Q(name__icontains=search)
                | Q(email__icontains=search)
                | Q(cpf__icontains=re.sub(r"[.\-\s]", "", search))
            )
        if request.GET.get("role"):
            query = query.filter(role=request.GET["role"])
        if request.GET.get("pending") == "true":
            query = query.filter(approved=False)
        return {"users": [serialize(u) for u in query]}
    with transaction.atomic():
        user = User(username=uuid.uuid4().hex, **identity(request.payload))
        require_change = request.payload.pop("must_change_password", True)
        if not isinstance(require_change, bool):
            raise ValueError("A opção de troca de senha deve ser verdadeira ou falsa.")
        selected = apply_permissions(request, user)
        user.set_password(password(request.payload))
        user.must_change_password = require_change
        user.save()
        user.courts.set(selected)
        audit(
            request,
            "user.created",
            user.pk,
            {"role": user.role, "courts": selected, "approved": user.approved},
        )
    return {"user": serialize(user)}


@api(["PATCH", "DELETE"])
def user_detail(request, user_id):
    management(request)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        management(request, user)
        if request.method == "DELETE":
            if request.user.role != "Master" or user.pk == request.user.pk:
                raise PermissionError("Você não pode excluir este usuário.")
            audit(request, "user.deleted", user.pk)
            user.delete()
            return {"message": "Usuário excluído."}
        reset_password = "password" in request.payload
        if reset_password:
            if request.user.role != "Master":
                raise PermissionError("Somente Master pode definir a senha de um usuário.")
            secret = password(request.payload)
            if secret != request.payload.get("password_confirmation"):
                raise ValueError("As senhas não coincidem.")
            user.set_password(secret)
            user.must_change_password = True
        elif "password_confirmation" in request.payload:
            raise ValueError("Informe a nova senha e sua confirmação.")
        old = serialize(user)
        for key, value in identity({**old, **request.payload}).items():
            setattr(user, key, value)
        # Merge omitted permissions without exposing internal fields to the caller.
        request.payload = {
            "role": old["role"],
            "status": old["status"],
            "courts": old["courts"],
            **request.payload,
        }
        selected = apply_permissions(request, user)
        user.save()
        user.courts.set(selected)
        if reset_password:
            audit(request, "password.reset_by_master", user.pk)
        audit(
            request,
            "user.updated",
            user.pk,
            {
                "before": {k: old[k] for k in ("role", "status", "courts")},
                "after": {"role": user.role, "status": request.payload["status"], "courts": selected},
            },
        )
    if reset_password and user.pk == request.user.pk:
        update_session_auth_hash(request, user)
    return {"user": serialize(user)}


@api(["GET"])
def audit_events(request):
    if request.user.role != "Master":
        raise PermissionError("Somente Master pode consultar a auditoria.")
    return {
        "events": list(
            AuditEvent.objects.order_by("-pk").values(
                "id", "created_at", "actor_name", "action", "target_id", "details"
            )[:200]
        )
    }
