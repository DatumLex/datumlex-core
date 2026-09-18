from django.urls import path

from src.routes import statistics

urlpatterns = [
    path("api/health/", statistics.health),
    path("api/scope/", statistics.scope),
    path("api/statistics/", statistics.statistics),
    path("api/distribution/", statistics.distribution),
    path("api/instances/", statistics.instances),
    path("api/processes/", statistics.processes),
]
