import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase


BACKEND = Path(__file__).resolve().parents[1]
VALID = {
    "DJANGO_DEBUG": "false",
    "DJANGO_SECRET_KEY": "isolated-test-secret-please-do-not-use-on-a-real-service-123",
    "DJANGO_SETTINGS_MODULE": "config.production_settings",
    "RESEARCH_CIVIL_COHORT": "civil-publication-fixture",
    "DATABASE_URL": "postgresql://fixture:fixture@datumlex-db-pedromattos.railway.internal/datumlex_release_fixture",
    "RAILWAY_ENVIRONMENT_NAME": "production",
    "RAILWAY_SERVICE_NAME": "datumlex-api-pedromattos",
    "DATUMLEX_PRODUCTION_API_HOST": "datumlex-api-pedromattos-production.up.railway.app",
    "DATUMLEX_PRODUCTION_FRONTEND_HOST": "datumlex-core.vercel.app",
}


class ProductionSettingsTests(SimpleTestCase):
    def run_production(self, script, overrides):
        env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT") if key in os.environ}
        env.update(VALID, **overrides)
        env["PYTHON_DOTENV_DISABLED"] = "1"
        return subprocess.run(
            [sys.executable, "-c", script], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=10,
        )

    def test_accepts_only_the_pinned_transport_settings(self):
        result = self.run_production("""
import json
from django.conf import settings
print(json.dumps({
    "hosts": settings.ALLOWED_HOSTS,
    "csrf": settings.CSRF_TRUSTED_ORIGINS,
    "cookie_secure": settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE,
    "csrf_http_only": settings.CSRF_COOKIE_HTTPONLY,
    "ssl": settings.DATABASES["default"]["OPTIONS"]["sslmode"],
    "cors": settings.CORS_ALLOWED_ORIGINS,
    "redirect": settings.SECURE_SSL_REDIRECT,
}))
""", {})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "hosts": [VALID["DATUMLEX_PRODUCTION_API_HOST"], "healthcheck.railway.app"],
            "csrf": ["https://datumlex-core.vercel.app"],
            "cookie_secure": True, "csrf_http_only": True, "ssl": "require", "cors": [], "redirect": True,
        })

    def test_rejects_unsafe_or_non_production_configuration(self):
        for overrides in (
            {"RAILWAY_ENVIRONMENT_NAME": "recovery-preview"},
            {"RAILWAY_SERVICE_NAME": "datumlex-api-preview"},
            {"DJANGO_DEBUG": "true"},
            {"DATUMLEX_PRODUCTION_FRONTEND_HOST": "*.vercel.app"},
            {"DATABASE_URL": VALID["DATABASE_URL"].replace("datumlex_release_fixture", "railway")},
            {"DATABASE_URL": VALID["DATABASE_URL"].replace("datumlex-db-pedromattos.railway.internal", "db.example.test")},
            {"DATUMLEX_PUBLIC_REGISTRATION_COURTS": "STJ"},
            {"RESEARCH_CIVIL_COHORT": ""},
            {"RESEARCH_GEMINI_ENABLED": "true"},
            {"DATAJUD_API_KEY": "fixture"},
        ):
            with self.subTest(overrides=overrides):
                result = self.run_production("from django.conf import settings; print(settings.DEBUG)", overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ImproperlyConfigured", result.stderr)

    def test_synthetic_production_requires_its_own_database_and_cohort(self):
        demo = {
            "DATUMLEX_PRODUCTION_DEMO": "true",
            "DATABASE_URL": VALID["DATABASE_URL"].replace("datumlex_release_fixture", "datumlex_release_synthetic"),
            "RESEARCH_CIVIL_COHORT": "civil-synthetic-production",
        }
        script = "from django.conf import settings; assert settings.SYNTHETIC_PREVIEW"
        result = self.run_production(script, demo)
        self.assertEqual(result.returncode, 0, result.stderr)
        for mismatch in (
            {"DATABASE_URL": VALID["DATABASE_URL"]},
            {"RESEARCH_CIVIL_COHORT": "civil-synthetic-4f"},
            {"DATUMLEX_PRODUCTION_DEMO": "false"},
        ):
            with self.subTest(mismatch=mismatch):
                result = self.run_production(script, demo | mismatch)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ImproperlyConfigured", result.stderr)

    def test_http_rejects_missing_session_csrf_and_foreign_origins(self):
        script = """
import django
django.setup()
from django.test import Client

client = Client(enforce_csrf_checks=True, HTTP_HOST="datumlex-api-pedromattos-production.up.railway.app")
assert client.get("/api/research/").status_code == 301
assert client.get("/api/research/", secure=True).status_code == 401
assert client.post("/api/auth/login/", secure=True).status_code == 403
assert not client.options("/api/auth/login/", secure=True, HTTP_ORIGIN="https://foreign.example").has_header(
    "Access-Control-Allow-Origin"
)
"""
        result = self.run_production(script, {})
        self.assertEqual(result.returncode, 0, result.stderr)
