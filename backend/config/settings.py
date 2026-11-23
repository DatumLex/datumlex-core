"""Local-first settings. PostgreSQL is selected explicitly through DATABASE_URL."""

import json
import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "local-development-only-datumlex")
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"
if not DEBUG and SECRET_KEY == "local-development-only-datumlex":
    raise ValueError("Set DJANGO_SECRET_KEY when DJANGO_DEBUG=false")
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",")
if render_hostname := os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(render_hostname)
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "src.db",
    "src.accounts",
]
AUTH_USER_MODEL = "accounts.User"
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "config.middleware.LocalCorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "src.accounts.middleware.AccessMiddleware",
]
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
CSRF_COOKIE_SAMESITE = os.environ.get("CSRF_COOKIE_SAMESITE", SESSION_COOKIE_SAMESITE)
SESSION_COOKIE_AGE = 28800
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_FAILURE_VIEW = "src.accounts.views.csrf_failure"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}}
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
database_url = os.environ.get("DATABASE_URL")
if database_url:
    url = urlparse(database_url)
    query_options = parse_qs(url.query)
    if url.scheme not in {"postgres", "postgresql"}:
        raise ValueError("DATABASE_URL must use PostgreSQL")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(url.path.lstrip("/")),
            "USER": unquote(url.username or ""),
            "PASSWORD": unquote(url.password or ""),
            "HOST": url.hostname,
            "PORT": url.port or 5432,
            "OPTIONS": {
                "sslmode": query_options.get("sslmode", ["prefer"])[0],
                "connect_timeout": int(query_options.get("connect_timeout", ["15"])[0]),
            },
        }
    }
else:
    DATABASES = {
        "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": DATA_DIR / "datumlex_v2.sqlite3"}
    }
CORS_ALLOWED_ORIGINS = os.environ.get(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174",
).split(",")
CSRF_TRUSTED_ORIGINS = os.environ.get("CSRF_TRUSTED_ORIGINS", ",".join(CORS_ALLOWED_ORIGINS)).split(",")
DATAJUD_API_KEY = os.environ.get("DATAJUD_API_KEY", "")
RESEARCH_CIVIL_COHORT = os.environ.get("RESEARCH_CIVIL_COHORT", "").strip()
PUBLIC_REGISTRATION_COURTS = tuple(
    dict.fromkeys(
        code.strip().upper()
        for code in os.environ.get("DATUMLEX_PUBLIC_REGISTRATION_COURTS", "").split(",")
        if code.strip()
    )
)
SYNTHETIC_PREVIEW = os.environ.get("DATUMLEX_SYNTHETIC_PREVIEW") == "true"
PREVIEW_REVISION = os.environ.get("DATUMLEX_PREVIEW_REVISION", "")
if SYNTHETIC_PREVIEW:
    if (
        DEBUG
        or os.environ.get("RAILWAY_ENVIRONMENT_NAME") != "recovery-preview"
        or os.environ.get("RAILWAY_SERVICE_NAME") != "datumlex-api-preview"
        or not database_url
        or DATABASES["default"]["HOST"] != "postgres.railway.internal"
        or DATABASES["default"]["NAME"] != "datumlex_preview_4f_demo"
        or RESEARCH_CIVIL_COHORT != "civil-synthetic-4f"
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("RESEARCH_GEMINI_ENABLED", "false").lower() != "false"
    ):
        raise ValueError("Invalid isolated synthetic preview configuration")
RESEARCH_GEMINI_ENABLED = os.environ.get("RESEARCH_GEMINI_ENABLED", "false").lower() == "true"
RESEARCH_GEMINI_MODEL = os.environ.get("RESEARCH_GEMINI_MODEL", "gemini-3.5-flash-lite")
RESEARCH_GEMINI_COOLDOWN_SECONDS = max(
    0, int(os.environ.get("RESEARCH_GEMINI_COOLDOWN_SECONDS", "8"))
)
NLP_DASHBOARD_CATALOG = {}
NLP_DASHBOARD_RELEASES = {}
_nlp_manifest_path = Path(__file__).resolve().parent / "nlp_v2_release_manifest.json"
if (
    not SYNTHETIC_PREVIEW
    and os.environ.get("NLP_DASHBOARD_USE_MANIFEST", "true").lower() != "false"
    and _nlp_manifest_path.exists()
):
    _nlp_manifest = json.loads(_nlp_manifest_path.read_text(encoding="utf-8"))
    NLP_DASHBOARD_CATALOG = _nlp_manifest.get("NLP_DASHBOARD_CATALOG", {})
    NLP_DASHBOARD_RELEASES = _nlp_manifest.get("NLP_DASHBOARD_RELEASES", {})
PANGEA_SEARCH_BASE_URL = os.environ.get(
    "PANGEA_SEARCH_BASE_URL", "https://pangeabnp.pdpj.jus.br"
).rstrip("/")
BNP_API_BASE_URL = os.environ.get("BNP_API_BASE_URL", "https://bnp-sempj.cloud.pje.jus.br").rstrip("/")
BNP_TOKEN_URL = os.environ.get(
    "BNP_TOKEN_URL",
    "https://sso.cloud.pje.jus.br/auth/realms/pje/protocol/openid-connect/token",
)
BNP_API_CLIENT_ID = os.environ.get("BNP_API_CLIENT_ID", "")
BNP_API_CLIENT_SECRET = os.environ.get("BNP_API_CLIENT_SECRET", "")
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')
