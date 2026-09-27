"""Run against a uniquely named temporary PostgreSQL database, removed by Django."""

import os
import uuid

from .settings import *  # noqa: F403

os.environ.pop("DATUMLEX_SUPPORT_PASSWORD", None)
if DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":  # noqa: F405
    raise RuntimeError("PostgreSQL test settings require DATABASE_URL.")
DATABASES["default"]["TEST"] = {"NAME": "test_datumlex_" + uuid.uuid4().hex[:12]}  # noqa: F405
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
