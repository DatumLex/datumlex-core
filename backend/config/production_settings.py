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


if os.environ.get("RAILWAY_ENVIRONMENT_NAME") != "production" or os.environ.get(
    "RAILWAY_SERVICE_NAME"
) != "datumlex-api-pedromattos":
    raise ImproperlyConfigured("Production settings require the DatumLex production API service.")
if DEBUG or SYNTHETIC_PREVIEW:  # noqa: F405
    raise ImproperlyConfigured("Production requires DEBUG and synthetic preview disabled.")
if len(SECRET_KEY) < 50:  # noqa: F405
    raise ImproperlyConfigured("Configure a dedicated production secret key.")
if PUBLIC_REGISTRATION_COURTS:  # noqa: F405
    raise ImproperlyConfigured("Public registration is closed in production.")
if not RESEARCH_CIVIL_COHORT:  # noqa: F405
    raise ImproperlyConfigured("Select the exact research cohort approved for this release.")
if RESEARCH_GEMINI_ENABLED or os.environ.get("GEMINI_API_KEY") or os.environ.get("DATAJUD_API_KEY"):  # noqa: F405
    raise ImproperlyConfigured("Production research starts with Gemini and collection disabled.")

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
