"""Local management command to materialize or audit the minimized real staging database."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from src.services.real_staging_prep import (
    EXPECTED_COHORT,
    StagingPrepError,
    audit_staging_database,
    materialize_minimized_staging,
    write_private_manifest,
)


def _register_pg_alias(alias: str, url_str: str) -> None:
    parsed = urlparse(url_str)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise StagingPrepError(f"URL do alias {alias!r} deve usar PostgreSQL.")
    opts = parse_qs(parsed.query)
    connections.databases[alias] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": parsed.port or 5432,
        "ATOMIC_REQUESTS": False,
        "AUTOCOMMIT": True,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "TIME_ZONE": None,
        "OPTIONS": {
            "sslmode": opts.get("sslmode", ["disable"])[0],
            "connect_timeout": int(opts.get("connect_timeout", ["15"])[0]),
        },
    }


class Command(BaseCommand):
    help = "Materialize or audit a minimized, sanitized local PostgreSQL staging DB (never publishes)."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--source-env", default="STAGING_SOURCE_DATABASE_URL")
        parser.add_argument("--target-env", default="STAGING_TARGET_DATABASE_URL")
        parser.add_argument("--cohort", default=EXPECTED_COHORT)
        parser.add_argument("--manifest", type=Path, help="Private output path for manifest JSON (mode 0600).")
        parser.add_argument("--audit-only", action="store_true", help="Audit target staging DB read-only.")

    def handle(self, **options):
        try:
            target_url = os.environ.get(options["target_env"], "")
            if not target_url:
                raise StagingPrepError(f"Variável de ambiente {options['target_env']} ausente.")
            _register_pg_alias("staging_target", target_url)

            if options["audit_only"]:
                result = audit_staging_database("staging_target", cohort_name=options["cohort"])
            else:
                source_url = os.environ.get(options["source_env"], "")
                if not source_url:
                    raise StagingPrepError(f"Variável de ambiente {options['source_env']} ausente.")
                _register_pg_alias("staging_source", source_url)
                result = materialize_minimized_staging(
                    "staging_source",
                    "staging_target",
                    cohort_name=options["cohort"],
                    allow_test_db=False,
                )
                if options["manifest"]:
                    manifest_sha = write_private_manifest(options["manifest"], result)
                    result["manifest_path"] = str(options["manifest"])
                    result["manifest_sha256"] = manifest_sha
        except StagingPrepError as exc:
            raise CommandError(str(exc)) from None
        finally:
            connections.close_all()

        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
