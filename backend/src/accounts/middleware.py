from django.http import JsonResponse

from .models import AuditEvent


def denied(message, status=403, code="forbidden"):
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


class AccessMiddleware:
    PUBLIC = {"/api/health/", "/api/auth/csrf/", "/api/auth/login/", "/api/auth/register/"}
    PASSWORD_ALLOWED = {"/api/auth/me/", "/api/auth/logout/", "/api/auth/password/"}
    DATA_ROUTES = {
        f"/api/{name}/" for name in ("scope", "statistics", "distribution", "instances", "processes")
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/api/") and request.path not in self.PUBLIC:
            if not request.user.is_authenticated:
                return denied("Entre na sua conta para continuar.", 401, "unauthenticated")
            if not request.user.approved or not request.user.is_active:
                return denied("Seu cadastro não está ativo.")
            if request.user.must_change_password and request.path not in self.PASSWORD_ALLOWED:
                return denied("Altere sua senha inicial para continuar.", code="password_change_required")
            if request.path in self.DATA_ROUTES:
                court = request.GET.get("court", "TJDFT")
                if not request.user.support and not request.user.courts.filter(code=court).exists():
                    return denied("Você não possui acesso a este tribunal.")
        response = self.get_response(request)
        if request.path.startswith("/api/"):
            response["Cache-Control"] = "no-store"
            if request.user.is_authenticated and request.user.support:
                AuditEvent.objects.create(
                    actor=request.user,
                    actor_name=request.user.name,
                    action="support.request",
                    details={"method": request.method, "path": request.path, "status": response.status_code},
                )
        return response
