"""Isolated unit tests for scripts/local_ops.py using mocks and temp dirs only.

Never touches live services, operational PostgreSQL, or real private files.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import local_ops  # noqa: E402


FAKE_SECRET = "SUPER_SECRET_LOCAL_PASS_987654"
FAKE_DB_URL = f"postgresql://datumlex:{FAKE_SECRET}@127.0.0.1:55437/datumlex_dev"


class FakeAdapter(local_ops.SystemAdapter):
    """Deterministic in-memory OS adapter for simulating all failure/success modes."""

    def __init__(self, config: local_ops.LocalConfig):
        self.config = config
        self.ports: dict[int, list[local_ops.ProcessInfo]] = {
            config.pg_port: [],
            config.django_port: [],
            config.vite_port: [],
        }
        self.pg_ready = False
        self.pg_start_ok = True
        self.pg_start_becomes_ready = True
        self.pg_start_calls = 0
        self.db_inspection = local_ops.DbInspection(
            ok=True,
            database=config.database_name,
            cohort_present=True,
            member_count=4518,
            available_courts=config.registration_courts,
        )
        self.http_responses: dict[str, local_ops.HttpResult] = {
            config.backend_health_url: local_ops.HttpResult(ok=False, status=None, error="connection refused"),
            config.frontend_url: local_ops.HttpResult(ok=False, status=None, error="connection refused"),
            config.proxy_health_url: local_ops.HttpResult(ok=False, status=None, error="connection refused"),
        }
        self.spawned: list[dict] = []
        self.django_becomes_healthy = True
        self.vite_becomes_healthy = True
        self.proxy_becomes_healthy = True
        self.npm_path: str | None = "/opt/homebrew/bin/npm"
        self.forbid_mutations = False
        self.sleep_calls = 0

    def which(self, binary: str) -> str | None:
        if binary == "npm":
            return self.npm_path
        return f"/usr/bin/{binary}"

    def tcp_listening(self, host: str, port: int, timeout: float = 1.0) -> bool:
        return bool(self.ports.get(port))

    def inspect_port(self, port: int) -> list[local_ops.ProcessInfo]:
        return list(self.ports.get(port, []))

    def pg_isready(self, host: str, port: int) -> tuple[bool, str]:
        if self.pg_ready:
            return True, f"{host}:{port} - accepting connections"
        return False, f"{host}:{port} - no response"

    def query_db_readonly(self, database_url: str, config: local_ops.LocalConfig) -> local_ops.DbInspection:
        self.last_queried_db_url = database_url
        return self.db_inspection

    def http_get(self, url: str, *, expect_json: bool = True, timeout: float = 3.0) -> local_ops.HttpResult:
        return self.http_responses.get(
            url,
            local_ops.HttpResult(ok=False, status=None, error="unexpected url"),
        )

    def start_postgres(self, config: local_ops.LocalConfig) -> tuple[bool, str]:
        if self.forbid_mutations:
            raise AssertionError("start_postgres não pode ser chamado em --check ou --dry-run")
        self.pg_start_calls += 1
        if not self.pg_start_ok:
            return False, "pg_ctl: failed to start server"
        if self.pg_start_becomes_ready:
            self.pg_ready = True
            self.ports[config.pg_port] = [
                local_ops.ProcessInfo(
                    pid=9001,
                    command="/opt/homebrew/bin/postgres",
                    args=f"postgres -D {config.paths.pg_data_dir.resolve()} -h 127.0.0.1 -p {config.pg_port}",
                )
            ]
        return True, "server started"

    def spawn_background(self, argv, *, cwd, env, log_path) -> int:
        if self.forbid_mutations:
            raise AssertionError("spawn_background não pode ser chamado em --check ou --dry-run")
        pid = 9100 + len(self.spawned)
        self.spawned.append({"pid": pid, "argv": list(argv), "cwd": Path(cwd), "env": dict(env), "log": Path(log_path)})
        joined = " ".join(argv)
        if "gunicorn" in joined:
            if self.django_becomes_healthy:
                self.ports[self.config.django_port] = [
                    local_ops.ProcessInfo(
                        pid=pid,
                        command="python3.13",
                        args=joined,
                        cwd=str(cwd),
                    )
                ]
                self.http_responses[self.config.backend_health_url] = local_ops.HttpResult(
                    ok=True,
                    status=200,
                    json_body={"status": "ok", "service": "datumlex-backend", "database": "postgresql"},
                )
        elif "run dev" in joined:
            if self.vite_becomes_healthy:
                self.ports[self.config.vite_port] = [
                    local_ops.ProcessInfo(
                        pid=pid,
                        command="node",
                        args=f"node vite --host 127.0.0.1 --port {self.config.vite_port} --strictPort",
                        cwd=str(cwd),
                    )
                ]
                self.http_responses[self.config.frontend_url] = local_ops.HttpResult(ok=True, status=200)
                if self.proxy_becomes_healthy:
                    self.http_responses[self.config.proxy_health_url] = local_ops.HttpResult(
                        ok=True,
                        status=200,
                        json_body={"status": "ok", "service": "datumlex-backend", "database": "postgresql"},
                    )
        return pid

    def sleep(self, seconds: float) -> None:
        self.sleep_calls += 1


class LocalOpsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="datumlex-local-ops-test-")
        root = Path(self.tmp.name)
        self.repo = root / "datumlex-core"
        self.recovery = root / "recuperacao"
        (self.repo / "backend").mkdir(parents=True)
        (self.repo / "frontend" / "node_modules").mkdir(parents=True)
        (self.recovery / "pg").mkdir(parents=True)
        (self.recovery / "socket").mkdir(parents=True)
        (self.recovery / "runtime" / "bin").mkdir(parents=True)
        (self.recovery / "runtime" / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")
        (self.recovery / "runtime" / "bin" / "gunicorn").write_text("#!/bin/sh\n", encoding="utf-8")
        self.env_file = self.recovery / "local-env"
        self.env_file.write_text(f"DATABASE_URL={FAKE_DB_URL}\n", encoding="utf-8")
        os.chmod(self.env_file, 0o600)

        self.paths = local_ops.LocalPaths(repo_root=self.repo, recovery_dir=self.recovery)
        self.config = local_ops.LocalConfig(
            paths=self.paths,
            startup_timeout_s=0.01,
            poll_interval_s=0.001,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _assert_no_secrets_leaked(self, report: local_ops.OpsReport):
        rendered_text = local_ops.format_report_text(report)
        rendered_json = json.dumps(
            {
                "mode": report.mode,
                "ok": report.ok,
                "checks": report.checks,
                "actions": report.actions,
                "warnings": report.warnings,
                "errors": report.errors,
                "final_url": report.final_url,
            },
            ensure_ascii=False,
        )
        for blob in (rendered_text, rendered_json):
            self.assertNotIn(FAKE_SECRET, blob)
            self.assertNotIn(FAKE_DB_URL, blob)

    def test_1_all_services_stopped_check_dry_run_and_start(self):
        # --check must never start or kill services
        adapter = FakeAdapter(self.config)
        adapter.forbid_mutations = True
        check_report = local_ops.run_diagnostic(self.config, adapter, base_env={})
        self.assertFalse(check_report.ok)
        self.assertFalse(check_report.checks["postgres"]["responding"])
        self.assertFalse(check_report.checks["django"]["responding"])
        self.assertFalse(check_report.checks["vite"]["responding"])
        self.assertFalse(check_report.checks["proxy_health"]["ok"])
        self._assert_no_secrets_leaked(check_report)

        # --dry-run must plan all three starts without spawning anything
        dry_report = local_ops.run_start(self.config, adapter, dry_run=True, base_env={})
        self.assertTrue(dry_report.ok)
        self.assertEqual(adapter.pg_start_calls, 0)
        self.assertEqual(adapter.spawned, [])
        self.assertTrue(any("PostgreSQL" in a for a in dry_report.actions))
        self.assertTrue(any("Django/Gunicorn" in a for a in dry_report.actions))
        self.assertTrue(any("React/Vite" in a for a in dry_report.actions))
        self._assert_no_secrets_leaked(dry_report)

        # Real start (with fake adapter) starts PG -> validates DB -> starts Gunicorn -> starts Vite
        adapter.forbid_mutations = False
        env_before = self.env_file.read_text(encoding="utf-8")
        start_report = local_ops.run_start(
            self.config,
            adapter,
            dry_run=False,
            base_env={"RESEARCH_GEMINI_ENABLED": "true", "DATUMLEX_SYNTHETIC_PREVIEW": "true"},
        )
        self.assertTrue(start_report.ok, start_report.errors)
        self.assertEqual(adapter.pg_start_calls, 1)
        self.assertEqual(len(adapter.spawned), 2)
        self.assertEqual(self.env_file.read_text(encoding="utf-8"), env_before)

        django_spawn, vite_spawn = adapter.spawned
        self.assertIn("127.0.0.1:58003", django_spawn["argv"])
        self.assertEqual(django_spawn["env"]["RESEARCH_CIVIL_COHORT"], "civil-2010-sgt-2026-11")
        self.assertEqual(
            django_spawn["env"]["DATUMLEX_PUBLIC_REGISTRATION_COURTS"],
            "STJ,TJDFT,TJMG,TJPR,TJRJ,TJRS,TJSP,TRF1,TRF3",
        )
        self.assertEqual(django_spawn["env"]["RESEARCH_GEMINI_ENABLED"], "false")
        self.assertEqual(django_spawn["env"]["GEMINI_API_KEY"], "")
        self.assertEqual(django_spawn["env"]["DATUMLEX_SYNTHETIC_PREVIEW"], "false")
        self.assertTrue(django_spawn["env"]["DATABASE_URL"].endswith("/datumlex_ops_f3_full"))
        self.assertEqual(vite_spawn["env"]["DATUMLEX_DEV_API_TARGET"], "http://127.0.0.1:58003")
        self.assertIn("--host", vite_spawn["argv"])
        self.assertIn("127.0.0.1", vite_spawn["argv"])
        self.assertIn("--strictPort", vite_spawn["argv"])
        self.assertIn("http://127.0.0.1:5173/", local_ops.format_report_text(start_report))
        self._assert_no_secrets_leaked(start_report)

    def test_2_services_already_running_not_duplicated(self):
        adapter = FakeAdapter(self.config)
        adapter.pg_ready = True
        adapter.ports[self.config.pg_port] = [
            local_ops.ProcessInfo(
                pid=1001,
                command="/opt/homebrew/bin/postgres",
                args=f"postgres -D {self.paths.pg_data_dir.resolve()} -h 127.0.0.1 -p 55437",
            )
        ]
        adapter.ports[self.config.django_port] = [
            local_ops.ProcessInfo(
                pid=1002,
                command="python3.13",
                args="python3.13 gunicorn --bind 127.0.0.1:58003 --workers 2 --reload config.wsgi:application",
                cwd=str(self.paths.backend_dir.resolve()),
            )
        ]
        adapter.ports[self.config.vite_port] = [
            local_ops.ProcessInfo(
                pid=1003,
                command="node",
                args="node vite --host 127.0.0.1 --port 5173 --strictPort",
                cwd=str(self.paths.frontend_dir.resolve()),
            )
        ]
        adapter.http_responses[self.config.backend_health_url] = local_ops.HttpResult(
            ok=True, status=200, json_body={"status": "ok", "database": "postgresql"}
        )
        adapter.http_responses[self.config.frontend_url] = local_ops.HttpResult(ok=True, status=200)
        adapter.http_responses[self.config.proxy_health_url] = local_ops.HttpResult(
            ok=True, status=200, json_body={"status": "ok", "database": "postgresql"}
        )

        check_report = local_ops.run_diagnostic(self.config, adapter, base_env={})
        self.assertTrue(check_report.ok, check_report.errors)
        self.assertTrue(check_report.checks["mode_and_ai"]["real_mode"])
        self.assertFalse(check_report.checks["mode_and_ai"]["synthetic_preview"])
        self.assertTrue(check_report.checks["database_readonly"]["ok"])

        start_report = local_ops.run_start(self.config, adapter, dry_run=False, base_env={})
        self.assertTrue(start_report.ok, start_report.errors)
        self.assertEqual(adapter.pg_start_calls, 0)
        self.assertEqual(adapter.spawned, [])
        self._assert_no_secrets_leaked(start_report)

    def test_3_postgres_unavailable_aborts_before_django_and_vite(self):
        adapter = FakeAdapter(self.config)
        adapter.pg_start_ok = False
        report = local_ops.run_start(self.config, adapter, dry_run=False, base_env={})
        self.assertFalse(report.ok)
        self.assertEqual(adapter.pg_start_calls, 1)
        self.assertEqual(adapter.spawned, [])
        self.assertTrue(any("PostgreSQL" in e for e in report.errors))
        self._assert_no_secrets_leaked(report)

    def test_4_backend_unavailable_aborts_before_vite(self):
        adapter = FakeAdapter(self.config)
        adapter.django_becomes_healthy = False
        report = local_ops.run_start(self.config, adapter, dry_run=False, base_env={})
        self.assertFalse(report.ok)
        self.assertEqual(len(adapter.spawned), 1)
        self.assertIn("gunicorn", " ".join(adapter.spawned[0]["argv"]))
        self.assertTrue(any("Django/Gunicorn" in e for e in report.errors))
        self._assert_no_secrets_leaked(report)

    def test_5_wrong_database_or_synthetic_mode_fails_closed(self):
        # 5a: local-env points to remote/wrong port
        self.env_file.write_text(
            f"DATABASE_URL=postgresql://user:{FAKE_SECRET}@postgres.railway.internal:5432/railway\n",
            encoding="utf-8",
        )
        adapter = FakeAdapter(self.config)
        report = local_ops.run_start(self.config, adapter, dry_run=False, base_env={})
        self.assertFalse(report.ok)
        self.assertEqual(adapter.pg_start_calls, 0)
        self.assertEqual(adapter.spawned, [])
        self._assert_no_secrets_leaked(report)

        # 5b: SQL read-only detects wrong database name or missing cohort
        self.env_file.write_text(f"DATABASE_URL={FAKE_DB_URL}\n", encoding="utf-8")
        adapter = FakeAdapter(self.config)
        adapter.db_inspection = local_ops.DbInspection(
            ok=True, database="datumlex_restore", cohort_present=False, member_count=0, available_courts=()
        )
        report = local_ops.run_start(self.config, adapter, dry_run=False, base_env={})
        self.assertFalse(report.ok)
        self.assertEqual(adapter.spawned, [])  # Django must NEVER be started against wrong DB
        self.assertTrue(any("diverge" in e for e in report.errors))
        self._assert_no_secrets_leaked(report)

        # 5c: Health endpoint reports synthetic preview mode
        adapter = FakeAdapter(self.config)
        adapter.pg_ready = True
        adapter.http_responses[self.config.backend_health_url] = local_ops.HttpResult(
            ok=True, status=200, json_body={"status": "ok", "database": "postgresql", "synthetic": True}
        )
        diag = local_ops.run_diagnostic(self.config, adapter, base_env={})
        self.assertFalse(diag.ok)
        self.assertTrue(diag.checks["django"]["synthetic"])
        self.assertTrue(any("SYNTHETIC_PREVIEW" in e for e in diag.errors))

    def test_6_missing_configuration_fails_cleanly(self):
        self.env_file.unlink()
        adapter = FakeAdapter(self.config)
        report = local_ops.run_start(self.config, adapter, dry_run=False, base_env={})
        self.assertFalse(report.ok)
        self.assertEqual(adapter.pg_start_calls, 0)
        self.assertEqual(adapter.spawned, [])
        self.assertTrue(any("local-env" in e for e in report.errors))

        # Restore local-env without DATABASE_URL
        self.env_file.write_text("OTHER_VAR=1\n", encoding="utf-8")
        report_no_url = local_ops.run_start(self.config, adapter, dry_run=False, base_env={})
        self.assertFalse(report_no_url.ok)
        self.assertTrue(any("DATABASE_URL" in e for e in report_no_url.errors))

    def test_7_unexpected_process_on_expected_port_aborts_safely(self):
        adapter = FakeAdapter(self.config)
        adapter.ports[self.config.django_port] = [
            local_ops.ProcessInfo(
                pid=7777,
                command="nginx",
                args="nginx: master process -c /etc/nginx.conf",
                cwd="/tmp",
            )
        ]
        check_report = local_ops.run_diagnostic(self.config, adapter, base_env={})
        self.assertFalse(check_report.ok)
        self.assertEqual(check_report.checks["ports"]["django"]["classification"], "unexpected")

        start_report = local_ops.run_start(self.config, adapter, dry_run=False, base_env={})
        self.assertFalse(start_report.ok)
        self.assertEqual(adapter.pg_start_calls, 0)
        self.assertEqual(adapter.spawned, [])
        self.assertTrue(any("inesperado" in e for e in start_report.errors))

    def test_8_partial_startup_failure_reports_exact_stage(self):
        # PostgreSQL already up, Django starts OK, Vite starts but proxy fails
        adapter = FakeAdapter(self.config)
        adapter.pg_ready = True
        adapter.ports[self.config.pg_port] = [
            local_ops.ProcessInfo(
                pid=1001,
                command="/opt/homebrew/bin/postgres",
                args=f"postgres -D {self.paths.pg_data_dir.resolve()} -h 127.0.0.1 -p 55437",
            )
        ]
        adapter.proxy_becomes_healthy = False
        report = local_ops.run_start(self.config, adapter, dry_run=False, base_env={})
        self.assertFalse(report.ok)
        self.assertEqual(adapter.pg_start_calls, 0)
        self.assertEqual(len(adapter.spawned), 2)
        self.assertTrue(any("Django/Gunicorn iniciado" in a for a in report.actions))
        self.assertTrue(any("Proxy" in e for e in report.errors))
        self.assertNotIn("Endereço local:", local_ops.format_report_text(report))

    def test_9_empty_gemini_key_blocks_dotenv_fallback(self):
        from dotenv import dotenv_values, load_dotenv

        dotenv_path = Path(self.tmp.name) / ".env"
        dotenv_path.write_text("GEMINI_API_KEY=should-never-load\nRESEARCH_GEMINI_ENABLED=true\n", encoding="utf-8")
        self.assertEqual(dotenv_values(dotenv_path)["GEMINI_API_KEY"], "should-never-load")
        backend_env = local_ops.build_backend_env({}, FAKE_DB_URL, self.config)
        with patch.dict(os.environ, backend_env, clear=True):
            load_dotenv(dotenv_path)
            self.assertEqual(os.environ["GEMINI_API_KEY"], "")
            self.assertEqual(os.environ["RESEARCH_GEMINI_ENABLED"], "false")

    def test_10_cli_check_json_never_leaks_credentials(self):
        adapter = FakeAdapter(self.config)
        adapter.forbid_mutations = True
        stdout = io.StringIO()
        with patch.object(local_ops, "SystemAdapter", return_value=adapter), patch("sys.stdout", stdout):
            code = local_ops.main(
                ["--check", "--json", "--repo-root", str(self.repo), "--recovery-dir", str(self.recovery)]
            )
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["mode"], "check")
        self.assertNotIn(FAKE_SECRET, stdout.getvalue())
        self.assertNotIn(FAKE_DB_URL, stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
