"""Isolated local tests: never provision deployment credentials or touch warehouse data."""

import os

from .settings import *  # noqa: F403

os.environ.pop("DATUMLEX_SUPPORT_PASSWORD", None)
PUBLIC_REGISTRATION_COURTS = ()
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
