from django.urls import path

from src.accounts import views as accounts
from src.routes import statistics

urlpatterns = [
    path("api/auth/csrf/", accounts.csrf),
    path("api/auth/register/", accounts.register),
    path("api/auth/login/", accounts.login),
    path("api/auth/logout/", accounts.logout),
    path("api/auth/me/", accounts.me),
    path("api/auth/password/", accounts.change_password),
    path("api/users/", accounts.users),
    path("api/users/<int:user_id>/", accounts.user_detail),
    path("api/audit/", accounts.audit_events),
    path("api/health/", statistics.health),
    path("api/scope/", statistics.scope),
    path("api/statistics/", statistics.statistics),
    path("api/distribution/", statistics.distribution),
    path("api/instances/", statistics.instances),
    path("api/processes/", statistics.processes),
]
