from django.urls import path

from src.accounts import views as accounts
from src.routes import nlp_dashboard, nlp_evidence, statistics

urlpatterns = [
    path('api/v2/filter-options/', nlp_dashboard.options),
    path('api/v2/analysis-snapshots/', nlp_dashboard.snapshots),
    path('api/v2/analysis-snapshots/<uuid:snapshot_id>/', nlp_dashboard.detail),
    path('api/v2/analysis-snapshots/<uuid:snapshot_id>/export/', nlp_dashboard.export),
    path('api/v2/analysis-snapshots/<uuid:snapshot_id>/report/', nlp_dashboard.report),
    path('api/v2/analysis-snapshots/<uuid:snapshot_id>/<str:resource>/', nlp_dashboard.ranking),
    path('api/v2/analysis-snapshots/<uuid:snapshot_id>/<str:resource>/<str:group_id>/sources/', nlp_dashboard.ranking),
    path('api/v1/extractions/<uuid:extraction_id>/', nlp_evidence.extraction),
    path('api/v1/extractions/<uuid:extraction_id>/evidences/', nlp_evidence.extraction_evidences),
    path('api/v1/evidences/<uuid:evidence_id>/', nlp_evidence.detail),
    path('api/v1/evidences/<uuid:evidence_id>/revisions/', nlp_evidence.revisions),
    path('api/v1/evidence-snapshots/', nlp_evidence.snapshots),
    path('api/v1/evidence-snapshots/<uuid:snapshot_id>/', nlp_evidence.snapshot_detail),
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
    path("api/alignment/", statistics.alignment),
]
