#!/usr/bin/env python3
"""Safe local diagnostics and startup controller for DatumLex presentation runs.

Never prints credentials, never runs migrations/ETL/restores, never kills existing
processes, and fails closed whenever the target operational database or cohort
cannot be verified.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

EXPECTED_HOST = "127.0.0.1"
EXPECTED_PG_PORT = 55437
EXPECTED_DJANGO_PORT = 58003
EXPECTED_VITE_PORT = 5173
EXPECTED_DATABASE = "datumlex_ops_f3_full"
EXPECTED_COHORT = "civil-2010-sgt-2026-11"
DEFAULT_DEMO_COURTS = (
    "STJ",
    "TJDFT",
    "TJMG",
    "TJPR",
    "TJRJ",
    "TJRS",
    "TJSP",
    "TRF1",
    "TRF3",
)
ACTIVE_COURTS = (*DEFAULT_DEMO_COURTS, "TST")
URL_CREDENTIALS_RE = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]+:)([^/\s@]+)(@)")


def redact_text(value: str) -> str:
    """Mask any URL credentials or inline secret assignments before display."""
    cleaned = URL_CREDENTIALS_RE.sub(r"\1***\3", value)
    cleaned = re.sub(
        r"(?i)\b(password|passwd|secret|token|api_key|database_url)\s*=\s*([^\s'\"`]+)",
        r"\1=***",
        cleaned,
    )
    return cleaned


@dataclass(frozen=True)
class LocalPaths:
    repo_root: Path
    recovery_dir: Path

    @property
    def backend_dir(self) -> Path:
        return self.repo_root / "backend"

    @property
    def frontend_dir(self) -> Path:
        return self.repo_root / "frontend"

    @property
    def local_env_file(self) -> Path:
        return self.recovery_dir / "local-env"

    @property
    def pg_data_dir(self) -> Path:
        return self.recovery_dir / "pg"

    @property
    def pg_socket_dir(self) -> Path:
        return self.recovery_dir / "socket"

    @property
    def pg_log_file(self) -> Path:
        return self.recovery_dir / "pg.log"

    @property
    def runtime_python(self) -> Path:
        return self.recovery_dir / "runtime" / "bin" / "python"

    @property
    def runtime_gunicorn(self) -> Path:
        return self.recovery_dir / "runtime" / "bin" / "gunicorn"

    @property
    def django_log_file(self) -> Path:
        return self.recovery_dir / "local-django.log"

    @property
    def vite_log_file(self) -> Path:
        return self.recovery_dir / "local-vite.log"

    @property
    def frontend_node_modules(self) -> Path:
        return self.frontend_dir / "node_modules"


@dataclass(frozen=True)
class LocalConfig:
    paths: LocalPaths
    host: str = EXPECTED_HOST
    pg_port: int = EXPECTED_PG_PORT
    django_port: int = EXPECTED_DJANGO_PORT
    vite_port: int = EXPECTED_VITE_PORT
    database_name: str = EXPECTED_DATABASE
    cohort: str = EXPECTED_COHORT
    registration_courts: tuple[str, ...] = DEFAULT_DEMO_COURTS
    startup_timeout_s: float = 20.0
    poll_interval_s: float = 0.4

    @property
    def backend_url(self) -> str:
        return f"http://{self.host}:{self.django_port}"

    @property
    def frontend_url(self) -> str:
        return f"http://{self.host}:{self.vite_port}/"

    @property
    def proxy_health_url(self) -> str:
        return f"http://{self.host}:{self.vite_port}/api/health/"

    @property
    def backend_health_url(self) -> str:
        return f"http://{self.host}:{self.django_port}/api/health/"


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    command: str
    args: str
    cwd: str = ""


@dataclass(frozen=True)
class PortCheck:
    port: int
    listening: bool
    classification: str  # "free", "expected", "unexpected"
    processes: tuple[ProcessInfo, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class HttpResult:
    ok: bool
    status: int | None
    json_body: dict[str, Any] | None = None
    error: str = ""


@dataclass(frozen=True)
class DbInspection:
    ok: bool
    database: str | None = None
    cohort_present: bool = False
    member_count: int = 0
    available_courts: tuple[str, ...] = ()
    error: str = ""


@dataclass
class OpsReport:
    mode: str
    ok: bool = True
    checks: dict[str, Any] = field(default_factory=dict)
    actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    final_url: str = ""


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines from an env file without executing shell code."""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        if key:
            values[key] = val
    return values


def resolve_registration_courts(raw_courts: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized = tuple(
        dict.fromkeys(
            code.strip().upper()
            for code in raw_courts
            if isinstance(code, str) and code.strip()
        )
    )
    invalid = [code for code in normalized if code not in ACTIVE_COURTS]
    if invalid:
        raise ValueError(f"Tribunais fora de ACTIVE_COURTS na configuração: {', '.join(invalid)}.")
    if not normalized:
        raise ValueError("DATUMLEX_PUBLIC_REGISTRATION_COURTS não pode ficar vazio na inicialização local.")
    return normalized


def build_safe_database_url(raw_url: str, config: LocalConfig) -> tuple[str, dict[str, Any]]:
    """Validate private local DATABASE_URL and target the exact operational DB.

    Returns (private_url_for_process, sanitized_summary_without_secrets).
    """
    if not raw_url or not isinstance(raw_url, str):
        raise ValueError("DATABASE_URL ausente em recuperacao/local-env.")
    parsed = urlsplit(raw_url.strip())
    if parsed.scheme not in ("postgres", "postgresql"):
        raise ValueError("DATABASE_URL deve usar esquema PostgreSQL.")
    if parsed.hostname not in ("127.0.0.1", "localhost"):
        raise ValueError("DATABASE_URL privada não aponta para loopback local (127.0.0.1/localhost).")
    if parsed.port != config.pg_port:
        raise ValueError(
            f"DATABASE_URL aponta para a porta {parsed.port}, diferente da porta isolada esperada ({config.pg_port})."
        )
    source_db = parsed.path.lstrip("/")
    if not source_db:
        raise ValueError("DATABASE_URL não informa o banco de origem.")
    effective_url = urlunsplit(parsed._replace(path=f"/{config.database_name}"))
    summary = {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port,
        "source_database_in_env_file": source_db,
        "effective_database": config.database_name,
        "has_credentials": bool(parsed.username or parsed.password),
    }
    return effective_url, summary


def build_backend_env(
    base_env: dict[str, str],
    effective_database_url: str,
    config: LocalConfig,
) -> dict[str, str]:
    """Build an explicit, safe process environment for Gunicorn/Django."""
    courts = resolve_registration_courts(config.registration_courts)
    env = dict(base_env)
    allowed_origins = f"http://localhost:{config.vite_port},http://127.0.0.1:{config.vite_port}"
    env.update(
        {
            "DATABASE_URL": effective_database_url,
            "DJANGO_SETTINGS_MODULE": "config.settings",
            "DJANGO_DEBUG": "true",
            "DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1,[::1]",
            "CORS_ALLOWED_ORIGINS": allowed_origins,
            "CSRF_TRUSTED_ORIGINS": allowed_origins,
            "RESEARCH_CIVIL_COHORT": config.cohort,
            "DATUMLEX_PUBLIC_REGISTRATION_COURTS": ",".join(courts),
            "DATUMLEX_SYNTHETIC_PREVIEW": "false",
            "RESEARCH_GEMINI_ENABLED": "false",
            # Empty string kept in os.environ so python-dotenv(override=False) will not load backend/.env's key.
            "GEMINI_API_KEY": "",
        }
    )
    return env


def build_frontend_env(base_env: dict[str, str], config: LocalConfig) -> dict[str, str]:
    env = dict(base_env)
    env["DATUMLEX_DEV_API_TARGET"] = config.backend_url
    return env


def classify_port_processes(
    service: str,
    port: int,
    processes: list[ProcessInfo],
    config: LocalConfig,
) -> PortCheck:
    if not processes:
        return PortCheck(port=port, listening=False, classification="free", detail="Porta livre.")
    expected_pg_dir = str(config.paths.pg_data_dir.resolve())
    expected_backend_dir = str(config.paths.backend_dir.resolve())
    expected_frontend_dir = str(config.paths.frontend_dir.resolve())

    def is_expected(proc: ProcessInfo) -> bool:
        comm_name = Path(proc.command).name.lower()
        args = proc.args
        cwd = proc.cwd
        if service == "postgres":
            return "postgres" in comm_name and expected_pg_dir in args
        if service == "django":
            is_gunicorn = "gunicorn" in args and "config.wsgi:application" in args
            matches_port = f"{config.host}:{config.django_port}" in args
            cwd_ok = (not cwd) or (Path(cwd).resolve() == Path(expected_backend_dir))
            return is_gunicorn and matches_port and cwd_ok
        if service == "vite":
            is_vite = "vite" in args.lower() and (
                f"--port {config.vite_port}" in args or f"--port={config.vite_port}" in args
            )
            cwd_ok = (not cwd) or (Path(cwd).resolve() == Path(expected_frontend_dir))
            return is_vite and cwd_ok
        return False

    matched = [proc for proc in processes if is_expected(proc)]
    sanitized = tuple(
        ProcessInfo(pid=p.pid, command=p.command, args=redact_text(p.args), cwd=p.cwd)
        for p in processes
    )
    if len(matched) == len(processes):
        return PortCheck(
            port=port,
            listening=True,
            classification="expected",
            processes=sanitized,
            detail=f"Serviço {service} local já ativo na porta {port}.",
        )
    return PortCheck(
        port=port,
        listening=True,
        classification="unexpected",
        processes=sanitized,
        detail=(
            f"Porta {port} ocupada por processo inesperado para {service}. "
            "Nenhum processo foi encerrado ou substituído."
        ),
    )


class SystemAdapter:
    """Real OS adapter used at runtime; replaced by fakes/mocks in isolated tests."""

    def which(self, binary: str) -> str | None:
        return shutil.which(binary)

    def tcp_listening(self, host: str, port: int, timeout: float = 1.0) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def inspect_port(self, port: int) -> list[ProcessInfo]:
        lsof_bin = shutil.which("lsof")
        if not lsof_bin:
            return []
        proc = subprocess.run(
            [lsof_bin, "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            check=False,
        )
        pids = sorted({int(line.strip()) for line in proc.stdout.splitlines() if line.strip().isdigit()})
        results: list[ProcessInfo] = []
        for pid in pids:
            comm_proc = subprocess.run(
                ["ps", "-o", "comm=", "-p", str(pid)],
                capture_output=True,
                text=True,
                check=False,
            )
            args_proc = subprocess.run(
                ["ps", "-o", "args=", "-p", str(pid)],
                capture_output=True,
                text=True,
                check=False,
            )
            comm = comm_proc.stdout.strip()
            args = args_proc.stdout.strip() or comm
            if not comm and not args:
                continue
            cwd = ""
            cwd_proc = subprocess.run(
                [lsof_bin, "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                capture_output=True,
                text=True,
                check=False,
            )
            for item in cwd_proc.stdout.splitlines():
                if item.startswith("n"):
                    cwd = item[1:].strip()
                    break
            results.append(ProcessInfo(pid=pid, command=comm, args=args, cwd=cwd))
        return results

    def pg_isready(self, host: str, port: int) -> tuple[bool, str]:
        pg_isready_bin = shutil.which("pg_isready")
        if not pg_isready_bin:
            return False, "Binário pg_isready não encontrado no PATH."
        proc = subprocess.run(
            [pg_isready_bin, "-h", host, "-p", str(port)],
            capture_output=True,
            text=True,
            check=False,
        )
        detail = (proc.stdout or proc.stderr or "").strip()
        return proc.returncode == 0, redact_text(detail)

    def http_get(self, url: str, *, expect_json: bool = True, timeout: float = 3.0) -> HttpResult:
        req = Request(url, headers={"Accept": "application/json" if expect_json else "text/html"})
        try:
            with urlopen(req, timeout=timeout) as resp:
                status = getattr(resp, "status", 200)
                raw = resp.read(65536)
                if expect_json:
                    data = json.loads(raw.decode("utf-8"))
                    if not isinstance(data, dict):
                        return HttpResult(ok=False, status=status, error="Resposta JSON inesperada.")
                    return HttpResult(ok=200 <= status < 300, status=status, json_body=data)
                return HttpResult(ok=200 <= status < 300, status=status)
        except HTTPError as exc:
            return HttpResult(ok=False, status=exc.code, error=f"HTTP {exc.code}")
        except (URLError, OSError, ValueError, UnicodeDecodeError) as exc:
            return HttpResult(ok=False, status=None, error=redact_text(str(exc)))

    def query_db_readonly(self, database_url: str, config: LocalConfig) -> DbInspection:
        try:
            import psycopg
        except ImportError:
            return self._query_db_readonly_via_runtime(database_url, config)

        try:
            with psycopg.connect(database_url, connect_timeout=5) as conn:
                conn.read_only = True
                with conn.cursor() as cur:
                    cur.execute("SET TRANSACTION READ ONLY")
                    cur.execute("SELECT current_database()")
                    db_name = cur.fetchone()[0]
                    cur.execute(
                        "SELECT id FROM warehouse_civilsamplingcohort WHERE name = %s",
                        (config.cohort,),
                    )
                    cohort_row = cur.fetchone()
                    cohort_present = cohort_row is not None
                    member_count = 0
                    if cohort_present:
                        cur.execute(
                            "SELECT COUNT(*) FROM warehouse_civilsamplemember WHERE cohort_id = %s",
                            (cohort_row[0],),
                        )
                        member_count = int(cur.fetchone()[0])
                    cur.execute("SELECT code FROM accounts_court ORDER BY code")
                    courts = tuple(row[0] for row in cur.fetchall())
                conn.rollback()
            return DbInspection(
                ok=True,
                database=db_name,
                cohort_present=cohort_present,
                member_count=member_count,
                available_courts=courts,
            )
        except Exception as exc:  # noqa: BLE001
            return DbInspection(ok=False, error=redact_text(str(exc)))

    def _query_db_readonly_via_runtime(self, database_url: str, config: LocalConfig) -> DbInspection:
        python_bin = config.paths.runtime_python
        if not python_bin.exists():
            return DbInspection(ok=False, error="psycopg indisponível e runtime Python não encontrado.")
        snippet = (
            "import json, os, psycopg\n"
            "with psycopg.connect(os.environ['DATUMLEX_CHECK_DB_URL'], connect_timeout=5) as conn:\n"
            "  conn.read_only = True\n"
            "  with conn.cursor() as cur:\n"
            "    cur.execute('SET TRANSACTION READ ONLY')\n"
            "    cur.execute('SELECT current_database()')\n"
            "    db = cur.fetchone()[0]\n"
            "    cur.execute('SELECT id FROM warehouse_civilsamplingcohort WHERE name = %s', (os.environ['DATUMLEX_CHECK_COHORT'],))\n"
            "    row = cur.fetchone()\n"
            "    count = 0\n"
            "    if row:\n"
            "      cur.execute('SELECT COUNT(*) FROM warehouse_civilsamplemember WHERE cohort_id = %s', (row[0],))\n"
            "      count = int(cur.fetchone()[0])\n"
            "    cur.execute('SELECT code FROM accounts_court ORDER BY code')\n"
            "    courts = [r[0] for r in cur.fetchall()]\n"
            "  conn.rollback()\n"
            "print(json.dumps({'database': db, 'cohort_present': row is not None, 'member_count': count, 'available_courts': courts}))\n"
        )
        env = dict(os.environ)
        env["DATUMLEX_CHECK_DB_URL"] = database_url
        env["DATUMLEX_CHECK_COHORT"] = config.cohort
        proc = subprocess.run(
            [str(python_bin), "-c", snippet],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return DbInspection(ok=False, error=redact_text((proc.stderr or proc.stdout).strip()))
        try:
            payload = json.loads(proc.stdout.strip())
        except ValueError as exc:
            return DbInspection(ok=False, error=f"Saída inesperada da inspeção SQL: {exc}")
        return DbInspection(
            ok=True,
            database=payload["database"],
            cohort_present=bool(payload["cohort_present"]),
            member_count=int(payload["member_count"]),
            available_courts=tuple(payload["available_courts"]),
        )

    def start_postgres(self, config: LocalConfig) -> tuple[bool, str]:
        pg_ctl = shutil.which("pg_ctl")
        if not pg_ctl:
            return False, "Binário pg_ctl não encontrado no PATH."
        config.paths.pg_socket_dir.mkdir(parents=True, exist_ok=True)
        opts = (
            f"-h {config.host} -p {config.pg_port} "
            f"-k {config.paths.pg_socket_dir} -c unix_socket_permissions=0700"
        )
        proc = subprocess.run(
            [
                pg_ctl,
                "-D",
                str(config.paths.pg_data_dir),
                "-l",
                str(config.paths.pg_log_file),
                "-o",
                opts,
                "start",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        output = redact_text((proc.stdout or proc.stderr or "").strip())
        return proc.returncode == 0, output

    def spawn_background(
        self,
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        log_path: Path,
    ) -> int:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as log_file:
            proc = subprocess.Popen(
                argv,
                cwd=str(cwd),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            return proc.pid

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def _health_is_real_postgres(result: HttpResult) -> tuple[bool, str]:
    if not result.ok or not result.json_body:
        return False, result.error or f"HTTP {result.status}"
    body = result.json_body
    if body.get("synthetic") is True:
        return False, "Instância respondendo em modo SYNTHETIC_PREVIEW (esperado: modo real)."
    if body.get("status") != "ok":
        return False, f"Status de saúde inesperado: {body.get('status')!r}."
    if body.get("database") != "postgresql":
        return False, f"Engine de banco inesperada: {body.get('database')!r} (esperado: 'postgresql')."
    return True, "ok"


def _validate_db_inspection(inspection: DbInspection, config: LocalConfig) -> list[str]:
    issues: list[str] = []
    if not inspection.ok:
        return [f"Falha na verificação SQL somente leitura: {inspection.error}"]
    if inspection.database != config.database_name:
        issues.append(
            f"Banco conectado ({inspection.database!r}) diverge do operacional esperado ({config.database_name!r})."
        )
    if not inspection.cohort_present:
        issues.append(f"Coorte esperada '{config.cohort}' não encontrada no banco {inspection.database}.")
    elif inspection.member_count <= 0:
        issues.append(f"Coorte '{config.cohort}' está vazia (0 membros) no banco {inspection.database}.")
    missing_courts = [c for c in config.registration_courts if c not in inspection.available_courts]
    if missing_courts:
        issues.append(
            f"Tribunais configurados ausentes em accounts_court: {', '.join(missing_courts)}."
        )
    return issues


def validate_static_prerequisites(
    config: LocalConfig,
    base_env: dict[str, str],
) -> tuple[str | None, dict[str, Any], list[str], list[str]]:
    """Validate configuration and filesystem prerequisites without revealing secrets."""
    errors: list[str] = []
    warnings: list[str] = []
    info: dict[str, Any] = {
        "repo_root": str(config.paths.repo_root),
        "recovery_dir": str(config.paths.recovery_dir),
        "expected_database": config.database_name,
        "expected_cohort": config.cohort,
        "registration_courts": [],
        "synthetic_preview_enforced": False,
        "gemini_disabled_enforced": True,
        "caller_env_gemini_enabled": base_env.get("RESEARCH_GEMINI_ENABLED", "").lower() == "true",
        "caller_env_synthetic_preview": base_env.get("DATUMLEX_SYNTHETIC_PREVIEW", "").lower() == "true",
    }

    try:
        courts = resolve_registration_courts(config.registration_courts)
        info["registration_courts"] = list(courts)
    except ValueError as exc:
        errors.append(str(exc))

    if info["caller_env_gemini_enabled"]:
        warnings.append(
            "O shell atual possui RESEARCH_GEMINI_ENABLED=true; o script forçará false e GEMINI_API_KEY vazia."
        )
    if info["caller_env_synthetic_preview"]:
        warnings.append(
            "O shell atual possui DATUMLEX_SYNTHETIC_PREVIEW=true; o script forçará false no modo local."
        )

    required_paths = [
        ("Diretório backend", config.paths.backend_dir),
        ("Diretório frontend", config.paths.frontend_dir),
        ("Cluster PostgreSQL isolado", config.paths.pg_data_dir),
        ("Runtime Python", config.paths.runtime_python),
        ("Gunicorn do runtime", config.paths.runtime_gunicorn),
        ("Dependências frontend (node_modules)", config.paths.frontend_node_modules),
    ]
    path_status: dict[str, bool] = {}
    for label, path in required_paths:
        exists = path.exists()
        path_status[label] = exists
        if not exists:
            errors.append(f"{label} não encontrado: {path}")
    info["paths"] = path_status

    effective_db_url: str | None = None
    env_file = config.paths.local_env_file
    if not env_file.exists():
        errors.append(f"Arquivo privado de conexão ausente: {env_file}")
    else:
        try:
            mode = env_file.stat().st_mode & 0o777
            if mode & 0o077:
                warnings.append(f"Permissões amplas em {env_file.name} ({oct(mode)}); recomendado 0o600.")
            parsed_env = parse_env_file(env_file)
            effective_db_url, db_summary = build_safe_database_url(parsed_env.get("DATABASE_URL", ""), config)
            info["database_config"] = db_summary
        except (OSError, ValueError) as exc:
            errors.append(redact_text(str(exc)))

    return effective_db_url, info, warnings, errors


def _inspect_ports(config: LocalConfig, adapter: SystemAdapter) -> dict[str, PortCheck]:
    mapping = {
        "postgres": config.pg_port,
        "django": config.django_port,
        "vite": config.vite_port,
    }
    checks: dict[str, PortCheck] = {}
    for service, port in mapping.items():
        procs = adapter.inspect_port(port)
        if not procs and adapter.tcp_listening(config.host, port):
            checks[service] = PortCheck(
                port=port,
                listening=True,
                classification="unexpected",
                detail=f"Porta {port} aceitando conexões, mas não foi possível identificar o processo.",
            )
        else:
            checks[service] = classify_port_processes(service, port, procs, config)
    return checks


def run_diagnostic(
    config: LocalConfig,
    adapter: SystemAdapter,
    *,
    base_env: dict[str, str] | None = None,
) -> OpsReport:
    """Strictly read-only diagnostic check. Never starts or stops any process."""
    env = os.environ if base_env is None else base_env
    report = OpsReport(mode="check", final_url=config.frontend_url)
    effective_db_url, cfg_info, warnings, cfg_errors = validate_static_prerequisites(config, dict(env))
    report.warnings.extend(warnings)
    report.errors.extend(cfg_errors)
    report.checks["configuration"] = cfg_info

    port_checks = _inspect_ports(config, adapter)
    report.checks["ports"] = {
        name: {
            "port": check.port,
            "listening": check.listening,
            "classification": check.classification,
            "detail": check.detail,
            "pids": [p.pid for p in check.processes],
        }
        for name, check in port_checks.items()
    }
    for name, check in port_checks.items():
        if check.classification == "unexpected":
            report.errors.append(check.detail)

    pg_ok, pg_detail = adapter.pg_isready(config.host, config.pg_port)
    report.checks["postgres"] = {"responding": pg_ok, "detail": pg_detail}
    if not pg_ok:
        report.errors.append(f"PostgreSQL não está respondendo em {config.host}:{config.pg_port}.")

    if pg_ok and effective_db_url:
        inspection = adapter.query_db_readonly(effective_db_url, config)
        db_issues = _validate_db_inspection(inspection, config)
        report.checks["database_readonly"] = {
            "ok": not db_issues,
            "database": inspection.database,
            "cohort_present": inspection.cohort_present,
            "member_count": inspection.member_count,
            "available_courts": list(inspection.available_courts),
            "issues": db_issues,
        }
        report.errors.extend(db_issues)
    else:
        report.checks["database_readonly"] = {
            "ok": False,
            "skipped": True,
            "reason": "PostgreSQL indisponível ou configuração de banco inválida.",
        }

    django_res = adapter.http_get(config.backend_health_url, expect_json=True)
    django_ok, django_detail = _health_is_real_postgres(django_res)
    report.checks["django"] = {
        "responding": django_res.ok,
        "valid_real_mode": django_ok,
        "status": django_res.status,
        "detail": django_detail,
        "synthetic": bool((django_res.json_body or {}).get("synthetic")),
    }
    if not django_ok:
        report.errors.append(f"Django ({config.backend_health_url}) indisponível ou inválido: {django_detail}")

    vite_res = adapter.http_get(config.frontend_url, expect_json=False)
    report.checks["vite"] = {
        "responding": vite_res.ok,
        "status": vite_res.status,
        "detail": "ok" if vite_res.ok else (vite_res.error or f"HTTP {vite_res.status}"),
    }
    if not vite_res.ok:
        report.errors.append(f"Vite ({config.frontend_url}) não está respondendo.")

    proxy_res = adapter.http_get(config.proxy_health_url, expect_json=True)
    proxy_ok, proxy_detail = _health_is_real_postgres(proxy_res)
    report.checks["proxy_health"] = {
        "ok": proxy_ok,
        "status": proxy_res.status,
        "detail": proxy_detail,
        "synthetic": bool((proxy_res.json_body or {}).get("synthetic")),
    }
    if not proxy_ok:
        report.errors.append(f"Proxy {config.proxy_health_url} falhou: {proxy_detail}")

    report.checks["mode_and_ai"] = {
        "real_mode": django_ok and proxy_ok and not bool((django_res.json_body or {}).get("synthetic")),
        "synthetic_preview": bool((django_res.json_body or {}).get("synthetic")),
        "gemini_disabled_in_script": True,
        "gemini_enabled_in_caller_shell": cfg_info["caller_env_gemini_enabled"],
    }

    report.ok = len(report.errors) == 0
    return report


def _wait_until(
    predicate: Callable[[], tuple[bool, str]],
    *,
    timeout_s: float,
    interval_s: float,
    sleep_fn: Callable[[float], None],
) -> tuple[bool, str]:
    deadline = time.monotonic() + timeout_s
    last_detail = ""
    while True:
        ok, detail = predicate()
        if ok:
            return True, detail
        last_detail = detail
        if time.monotonic() >= deadline:
            return False, last_detail
        sleep_fn(interval_s)


def run_start(
    config: LocalConfig,
    adapter: SystemAdapter,
    *,
    dry_run: bool = False,
    base_env: dict[str, str] | None = None,
) -> OpsReport:
    """Start missing local DatumLex services safely without duplicating or killing."""
    env = dict(os.environ if base_env is None else base_env)
    report = OpsReport(mode="dry-run" if dry_run else "start", final_url=config.frontend_url)

    effective_db_url, cfg_info, warnings, cfg_errors = validate_static_prerequisites(config, env)
    report.warnings.extend(warnings)
    report.errors.extend(cfg_errors)
    report.checks["configuration"] = cfg_info

    port_checks = _inspect_ports(config, adapter)
    report.checks["ports"] = {
        name: {
            "port": check.port,
            "listening": check.listening,
            "classification": check.classification,
            "detail": check.detail,
            "pids": [p.pid for p in check.processes],
        }
        for name, check in port_checks.items()
    }
    for check in port_checks.values():
        if check.classification == "unexpected":
            report.errors.append(check.detail)

    if report.errors or not effective_db_url:
        report.ok = False
        return report

    # 1. PostgreSQL
    pg_ok, _ = adapter.pg_isready(config.host, config.pg_port)
    if pg_ok and port_checks["postgres"].classification == "expected":
        report.actions.append(f"PostgreSQL já ativo em {config.host}:{config.pg_port} (mantido sem duplicar).")
    elif not pg_ok and port_checks["postgres"].classification == "free":
        if dry_run:
            report.actions.append(
                f"[dry-run] Iniciaria PostgreSQL 17 isolado em {config.host}:{config.pg_port}."
            )
        else:
            started, detail = adapter.start_postgres(config)
            if not started:
                report.errors.append(f"Falha ao iniciar PostgreSQL isolado: {detail}")
                report.ok = False
                return report
            ready, ready_detail = _wait_until(
                lambda: adapter.pg_isready(config.host, config.pg_port),
                timeout_s=config.startup_timeout_s,
                interval_s=config.poll_interval_s,
                sleep_fn=adapter.sleep,
            )
            if not ready:
                report.errors.append(
                    f"PostgreSQL não respondeu em {config.host}:{config.pg_port}: {ready_detail}"
                )
                report.ok = False
                return report
            report.actions.append(f"PostgreSQL 17 iniciado em {config.host}:{config.pg_port}.")
    else:
        report.errors.append(
            f"Estado inconsistente do PostgreSQL na porta {config.pg_port}. Abortando com segurança."
        )
        report.ok = False
        return report

    # Validate operational database BEFORE starting Django (fail-closed)
    if not dry_run or pg_ok:
        inspection = adapter.query_db_readonly(effective_db_url, config)
        db_issues = _validate_db_inspection(inspection, config)
        report.checks["database_readonly"] = {
            "ok": not db_issues,
            "database": inspection.database,
            "cohort_present": inspection.cohort_present,
            "member_count": inspection.member_count,
            "available_courts": list(inspection.available_courts),
            "issues": db_issues,
        }
        if db_issues:
            report.errors.extend(db_issues)
            report.ok = False
            return report
    else:
        report.actions.append(
            f"[dry-run] Validaria em leitura o banco {config.database_name} e a coorte {config.cohort}."
        )

    # 2. Django / Gunicorn
    django_res = adapter.http_get(config.backend_health_url, expect_json=True)
    django_ok, django_detail = _health_is_real_postgres(django_res)
    if port_checks["django"].classification == "expected":
        if not django_ok:
            report.errors.append(
                f"Gunicorn já ocupa a porta {config.django_port}, mas /api/health/ falhou ({django_detail}). "
                "Nenhum processo foi encerrado."
            )
            report.ok = False
            return report
        report.actions.append(f"Django/Gunicorn já ativo em {config.backend_url} (mantido sem duplicar).")
        report.warnings.append(
            "Gunicorn já estava em execução antes do script; variáveis de ambiente do processo existente "
            "(como DATUMLEX_PUBLIC_REGISTRATION_COURTS) não foram alteradas."
        )
    else:
        backend_argv = [
            str(config.paths.runtime_gunicorn),
            "--bind",
            f"{config.host}:{config.django_port}",
            "--workers",
            "2",
            "--reload",
            "config.wsgi:application",
        ]
        if dry_run:
            report.actions.append(
                f"[dry-run] Iniciaria Django/Gunicorn em {config.backend_url} "
                f"(banco {config.database_name}, coorte {config.cohort}, Gemini desativado, "
                f"{len(config.registration_courts)} tribunais no cadastro)."
            )
        else:
            backend_env = build_backend_env(env, effective_db_url, config)
            pid = adapter.spawn_background(
                backend_argv,
                cwd=config.paths.backend_dir,
                env=backend_env,
                log_path=config.paths.django_log_file,
            )
            healthy, health_detail = _wait_until(
                lambda: _health_is_real_postgres(
                    adapter.http_get(config.backend_health_url, expect_json=True)
                ),
                timeout_s=config.startup_timeout_s,
                interval_s=config.poll_interval_s,
                sleep_fn=adapter.sleep,
            )
            if not healthy:
                report.errors.append(
                    f"Django/Gunicorn (PID {pid}) não ficou saudável em {config.backend_health_url}: "
                    f"{health_detail}. Consulte {config.paths.django_log_file}."
                )
                report.ok = False
                return report
            report.actions.append(f"Django/Gunicorn iniciado em {config.backend_url} (PID {pid}).")

    # 3. React / Vite
    vite_res = adapter.http_get(config.frontend_url, expect_json=False)
    if port_checks["vite"].classification == "expected":
        if not vite_res.ok:
            report.errors.append(
                f"Vite já ocupa a porta {config.vite_port}, mas não respondeu HTTP 200. "
                "Nenhum processo foi encerrado."
            )
            report.ok = False
            return report
        report.actions.append(f"Vite já ativo em {config.frontend_url} (mantido sem duplicar).")
    else:
        npm_bin = adapter.which("npm")
        if not npm_bin:
            report.errors.append("Binário npm não encontrado no PATH.")
            report.ok = False
            return report
        vite_argv = [
            npm_bin,
            "run",
            "dev",
            "--",
            "--host",
            config.host,
            "--port",
            str(config.vite_port),
            "--strictPort",
        ]
        if dry_run:
            report.actions.append(
                f"[dry-run] Iniciaria React/Vite em {config.frontend_url} "
                f"com DATUMLEX_DEV_API_TARGET={config.backend_url}."
            )
        else:
            frontend_env = build_frontend_env(env, config)
            pid = adapter.spawn_background(
                vite_argv,
                cwd=config.paths.frontend_dir,
                env=frontend_env,
                log_path=config.paths.vite_log_file,
            )
            ready_vite, vite_detail = _wait_until(
                lambda: (
                    (res := adapter.http_get(config.frontend_url, expect_json=False)).ok,
                    res.error or f"HTTP {res.status}",
                ),
                timeout_s=config.startup_timeout_s,
                interval_s=config.poll_interval_s,
                sleep_fn=adapter.sleep,
            )
            if not ready_vite:
                report.errors.append(
                    f"Vite (PID {pid}) não respondeu em {config.frontend_url}: {vite_detail}. "
                    f"Consulte {config.paths.vite_log_file}."
                )
                report.ok = False
                return report
            report.actions.append(f"React/Vite iniciado em {config.frontend_url} (PID {pid}).")

    # 4. End-to-end proxy verification (skipped only in dry-run when services are down)
    if not dry_run:
        proxy_ok, proxy_detail = _wait_until(
            lambda: _health_is_real_postgres(adapter.http_get(config.proxy_health_url, expect_json=True)),
            timeout_s=config.startup_timeout_s,
            interval_s=config.poll_interval_s,
            sleep_fn=adapter.sleep,
        )
        report.checks["proxy_health"] = {"ok": proxy_ok, "detail": proxy_detail}
        if not proxy_ok:
            report.errors.append(f"Proxy {config.proxy_health_url} falhou após inicialização: {proxy_detail}")
            report.ok = False
            return report

    report.ok = True
    return report


def format_report_text(report: OpsReport) -> str:
    lines = [f"DatumLex local ({report.mode}) · status: {'OK' if report.ok else 'FALHA'}"]
    cfg = report.checks.get("configuration", {})
    if cfg:
        db_cfg = cfg.get("database_config", {})
        lines.append(
            f"- Banco alvo: {cfg.get('expected_database')} · Coorte: {cfg.get('expected_cohort')} "
            f"· Host/Porta PG: {db_cfg.get('host', 'n/d')}:{db_cfg.get('port', 'n/d')}"
        )
        courts = cfg.get("registration_courts") or []
        lines.append(f"- Tribunais no cadastro público ({len(courts)}): {', '.join(courts) or 'nenhum'}")
        lines.append("- Modo sintético: desativado (false) · Gemini: desativado (false)")

    ports = report.checks.get("ports", {})
    if ports:
        lines.append("- Portas:")
        for name, item in ports.items():
            pids = f" (PIDs: {', '.join(map(str, item['pids']))})" if item["pids"] else ""
            lines.append(f"  * {name} ({item['port']}): {item['classification']}{pids} — {item['detail']}")

    for key, label in (
        ("postgres", "PostgreSQL"),
        ("django", "Django"),
        ("vite", "Vite"),
        ("proxy_health", "Proxy /api/health/"),
    ):
        if key in report.checks:
            item = report.checks[key]
            ok_flag = item.get("valid_real_mode", item.get("responding", item.get("ok", False)))
            lines.append(f"- {label}: {'OK' if ok_flag else 'INDISPONÍVEL'} ({item.get('detail', '')})")

    db_ro = report.checks.get("database_readonly")
    if db_ro:
        if db_ro.get("skipped"):
            lines.append(f"- Verificação SQL somente leitura: ignorada ({db_ro.get('reason')})")
        else:
            lines.append(
                f"- Verificação SQL somente leitura: {'OK' if db_ro.get('ok') else 'FALHA'} "
                f"(banco={db_ro.get('database')}, coorte={db_ro.get('cohort_present')}, "
                f"membros={db_ro.get('member_count')}, tribunais={len(db_ro.get('available_courts', []))})"
            )

    if report.actions:
        lines.append("- Ações:")
        for action in report.actions:
            lines.append(f"  * {action}")
    if report.warnings:
        lines.append("- Avisos:")
        for warning in report.warnings:
            lines.append(f"  * {warning}")
    if report.errors:
        lines.append("- Erros:")
        for err in report.errors:
            lines.append(f"  * {err}")
    if report.ok:
        lines.append(f"- Endereço local: {report.final_url}")
    return "\n".join(lines)


def default_paths() -> LocalPaths:
    repo_root = Path(__file__).resolve().parent.parent
    recovery_dir = Path(os.environ.get("DATUMLEX_RECOVERY_DIR", str(repo_root.parent / "recuperacao"))).resolve()
    return LocalPaths(repo_root=repo_root, recovery_dir=recovery_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Diagnóstico e inicialização local segura do DatumLex (sem alterar dados nem expor segredos)."
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("check", "start"),
        default=None,
        help="Ação principal: 'check' (somente leitura) ou 'start' (inicia apenas serviços ausentes).",
    )
    parser.add_argument("--check", action="store_true", help="Executa apenas o diagnóstico somente leitura.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simula a inicialização sem iniciar nem encerrar processos.",
    )
    parser.add_argument("--json", action="store_true", help="Emite o relatório sanitizado em JSON.")
    parser.add_argument("--repo-root", type=Path, default=None, help="Diretório do repositório DatumLex.")
    parser.add_argument("--recovery-dir", type=Path, default=None, help="Diretório privado de recuperação.")
    args = parser.parse_args(argv)

    paths = default_paths()
    if args.repo_root is not None:
        paths = LocalPaths(repo_root=args.repo_root.resolve(), recovery_dir=paths.recovery_dir)
    if args.recovery_dir is not None:
        paths = LocalPaths(repo_root=paths.repo_root, recovery_dir=args.recovery_dir.resolve())

    config = LocalConfig(paths=paths)
    adapter = SystemAdapter()

    if args.check or args.command == "check" or (args.command is None and not args.dry_run):
        report = run_diagnostic(config, adapter)
    else:
        report = run_start(config, adapter, dry_run=args.dry_run)

    if args.json:
        print(
            json.dumps(
                {
                    "mode": report.mode,
                    "ok": report.ok,
                    "checks": report.checks,
                    "actions": report.actions,
                    "warnings": report.warnings,
                    "errors": report.errors,
                    "final_url": report.final_url if report.ok else "",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(format_report_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
