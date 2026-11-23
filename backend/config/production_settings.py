"""Explicit Railway production configuration. Defaults fail before connecting."""

import os
import re
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403


def required_host(name):
    host = os.environ.get(name, "").strip().lower()
    if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}", host):
        raise ImproperlyConfigured(f"Set {name} to an exact public hostname.")
    return host


SYNTHETIC_API_SERVICE = "datumlex-api-pedromattos"
REAL_API_SERVICE = "datumlex-api-real"
PRODUCTION_SERVICES = {SYNTHETIC_API_SERVICE, REAL_API_SERVICE}
SYNTHETIC_DATABASE_PATH = "/datumlex_release_synthetic"
SYNTHETIC_COHORT = "civil-synthetic-production"
REAL_DATABASE_PATH = "/datumlex_release_real_civil_2026_11"
REAL_COHORT = "civil-2010-sgt-2026-11"

RAILWAY_SERVICE = os.environ.get("RAILWAY_SERVICE_NAME")
if os.environ.get("RAILWAY_ENVIRONMENT_NAME") != "production" or RAILWAY_SERVICE not in PRODUCTION_SERVICES:
    raise ImproperlyConfigured("Production settings require the DatumLex production API service.")
if DEBUG or SYNTHETIC_PREVIEW:  # noqa: F405
    raise ImproperlyConfigured("Production requires DEBUG and synthetic preview disabled.")
PRODUCTION_DEMO = os.environ.get("DATUMLEX_PRODUCTION_DEMO") == "true"

if len(SECRET_KEY) < 50:  # noqa: F405
    raise ImproperlyConfigured("Configure a dedicated production secret key.")
if PUBLIC_REGISTRATION_COURTS:  # noqa: F405
    raise ImproperlyConfigured("Public registration is closed in production.")
if not RESEARCH_CIVIL_COHORT:  # noqa: F405
    raise ImproperlyConfigured("Select the exact research cohort approved for this release.")
if DATAJUD_API_KEY or os.environ.get("DATAJUD_API_KEY"):  # noqa: F405
    raise ImproperlyConfigured("Production research starts with DataJud collection disabled.")

has_gemini_key = bool(GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY"))  # noqa: F405
if RAILWAY_SERVICE == REAL_API_SERVICE and RESEARCH_GEMINI_ENABLED:  # noqa: F405
    if not has_gemini_key:
        raise ImproperlyConfigured("Enable Gemini on datumlex-api-real only with GEMINI_API_KEY configured.")
    if not re.fullmatch(r"gemini-[a-z0-9.-]{1,70}", RESEARCH_GEMINI_MODEL):  # noqa: F405
        raise ImproperlyConfigured("Configure a valid RESEARCH_GEMINI_MODEL for datumlex-api-real.")
elif RESEARCH_GEMINI_ENABLED or has_gemini_key:  # noqa: F405
    raise ImproperlyConfigured("Production research requires explicit Gemini enablement on datumlex-api-real only.")

api_host = required_host("DATUMLEX_PRODUCTION_API_HOST")
frontend_host = required_host("DATUMLEX_PRODUCTION_FRONTEND_HOST")
if api_host == frontend_host:
    raise ImproperlyConfigured("Configure distinct exact frontend and Railway hosts.")

private_db = urlsplit(os.environ.get("DATABASE_URL", ""))
if (
    private_db.scheme not in {"postgres", "postgresql"}
    or private_db.hostname != "datumlex-db-pedromattos.railway.internal"
    or not private_db.path.startswith("/datumlex_release_")
    or not private_db.username
    or not private_db.password
):
    raise ImproperlyConfigured("Use a dedicated release database on the private production PostgreSQL service.")

if RAILWAY_SERVICE == REAL_API_SERVICE:
    if (
        PRODUCTION_DEMO
        or private_db.path != REAL_DATABASE_PATH
        or RESEARCH_CIVIL_COHORT != REAL_COHORT  # noqa: F405
    ):
        raise ImproperlyConfigured("The real production API requires its dedicated database, cohort, and non-demo mode.")
elif private_db.path == REAL_DATABASE_PATH or RESEARCH_CIVIL_COHORT == REAL_COHORT:  # noqa: F405
    raise ImproperlyConfigured("The real release database and cohort are restricted to datumlex-api-real.")
elif PRODUCTION_DEMO:
    if (
        private_db.path != SYNTHETIC_DATABASE_PATH
        or RESEARCH_CIVIL_COHORT != SYNTHETIC_COHORT  # noqa: F405
    ):
        raise ImproperlyConfigured("The production demonstration requires its dedicated database and cohort.")
    SYNTHETIC_PREVIEW = True
elif private_db.path == SYNTHETIC_DATABASE_PATH:
    raise ImproperlyConfigured("The synthetic database requires the demonstration mode.")

DATABASES["default"]["OPTIONS"]["sslmode"] = "require"  # noqa: F405
ALLOWED_HOSTS = [api_host, "healthcheck.railway.app"]
CSRF_TRUSTED_ORIGINS = [f"https://{frontend_host}"]
# Browser requests use Vercel's same-origin proxy.
CORS_ALLOWED_ORIGINS = []
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]
SECURE_HSTS_SECONDS = 3600
SECURE_REFERRER_POLICY = "no-referrer"
