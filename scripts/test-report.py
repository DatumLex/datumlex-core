"""Run the DatumLex test suites and replace the local HTML coverage report."""

import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
OUTPUT = ROOT / "output" / "coverage" / "index.html"
COVERAGE_KEYS = ("covered_lines", "num_statements", "covered_branches", "num_branches")


@dataclass
class Suite:
    cases: dict | None = None
    coverage: dict | None = None
    files: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def run(command, cwd, env=None):
    try:
        return subprocess.run(command, cwd=cwd, env=env, check=False).returncode
    except OSError as error:
        print(error, file=sys.stderr)
        return 1


def backend_python():
    path = BACKEND / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(path) if path.is_file() else sys.executable


def backend_run(directory, title, coverage_args, tests):
    print(f"\n{title}", flush=True)
    env = os.environ.copy()
    env.update(COVERAGE_FILE=str(directory / ".coverage"), PYTHON_DOTENV_DISABLED="1")
    xml_file = directory / "pytest.xml"
    json_file = directory / "coverage.json"
    coverage = [backend_python(), "-m", "coverage"]
    status = run(
        [
            *coverage,
            "run",
            "--branch",
            *coverage_args,
            "-m",
            "pytest",
            "--ds=config.test_settings",
            "-p",
            "no:cacheprovider",
            "-q",
            "-rs",
            "--junitxml",
            str(xml_file),
            *tests,
        ],
        BACKEND,
        env,
    )
    suite = Suite()
    if status:
        suite.errors.append(f"A execução do pytest retornou código {status}. Confira a saída no terminal.")
    if xml_file.is_file():
        read_pytest(xml_file, suite)
    else:
        suite.errors.append("O pytest não gerou resultados. Confira as dependências em requirements-dev.txt.")
    if not (directory / ".coverage").is_file() or run(
        [*coverage, "json", "-o", str(json_file)], BACKEND, env
    ):
        suite.errors.append("A cobertura Python não pôde ser coletada.")
    else:
        read_python_coverage(json_file, suite)
    return suite


def read_pytest(path, suite):
    result = ET.parse(path).getroot().find("testsuite")
    total, skipped = int(result.get("tests")), int(result.get("skipped"))
    failed = int(result.get("failures")) + int(result.get("errors"))
    suite.cases = {
        "total": total,
        "passed": total - skipped - failed,
        "skipped": skipped,
        "failed": failed,
        "time": float(result.get("time")),
    }
    for case in result.findall("testcase"):
        skipped_case = case.find("skipped")
        name = ".".join(filter(None, [case.get("classname"), case.get("name")]))
        if skipped_case is not None:
            reason = skipped_case.get("message", "").removeprefix("Skipped: ")
            suite.notes.append(f"Pulado: {name} ({reason})")
        elif case.find("failure") is not None or case.find("error") is not None:
            suite.notes.append(f"Falhou: {name}")


def read_python_coverage(path, suite):
    coverage = json.loads(path.read_text(encoding="utf-8"))
    suite.coverage = {key: coverage["totals"][key] for key in COVERAGE_KEYS}
    suite.files = [
        {
            "name": "backend/" + name.replace("\\", "/"),
            **{key: result["summary"][key] for key in COVERAGE_KEYS},
            "missing": ranges(result["missing_lines"]),
        }
        for name, result in coverage["files"].items()
    ]


def frontend_run(directory):
    print("\nFrontend · testes unitários", flush=True)
    tap_file, lcov_file = directory / "frontend.tap", directory / "frontend.lcov"
    status = run(
        [
            "node",
            "--experimental-test-coverage",
            "--test-coverage-include=src/**/*.js",
            "--test-coverage-include=src/**/*.jsx",
            "--test-reporter=tap",
            "--test-reporter=lcov",
            f"--test-reporter-destination={tap_file}",
            f"--test-reporter-destination={lcov_file}",
            "--test",
            "tests/unit/*.test.mjs",
        ],
        FRONTEND,
    )
    suite = Suite()
    if status:
        suite.errors.append(f"A execução do Node.js retornou código {status}. Confira a saída no terminal.")
    if tap_file.is_file():
        tap = tap_file.read_text(encoding="utf-8")
        fields = dict(
            re.findall(
                r"^# (tests|pass|fail|cancelled|skipped|todo|duration_ms) ([\d.]+)$",
                tap,
                re.MULTILINE,
            )
        )
        if len(fields) == 7:
            suite.cases = {
                "total": int(fields["tests"]),
                "passed": int(fields["pass"]),
                "skipped": int(fields["skipped"]) + int(fields["todo"]),
                "failed": int(fields["fail"]) + int(fields["cancelled"]),
                "time": float(fields["duration_ms"]) / 1000,
            }
        if status:
            print(tap, file=sys.stderr)
    if not suite.cases:
        suite.errors.append("O executor do Node.js não gerou resultados.")
    if lcov_file.is_file():
        read_lcov(lcov_file, suite)
    if not suite.files:
        suite.errors.append("A cobertura do frontend não pôde ser coletada.")
    return suite


def read_lcov(path, suite):
    for record in path.read_text(encoding="utf-8").split("end_of_record"):
        values = dict(re.findall(r"^(SF|LF|LH|BRF|BRH|FNF|FNH):(.+)$", record, re.MULTILINE))
        if not values:
            continue
        uncovered = [int(line) for line in re.findall(r"^DA:(\d+),0(?:,.*)?$", record, re.MULTILINE)]
        suite.files.append(
            {
                "name": "frontend/" + values["SF"].replace("\\", "/"),
                "covered_lines": int(values["LH"]),
                "num_statements": int(values["LF"]),
                "covered_branches": int(values["BRH"]),
                "num_branches": int(values["BRF"]),
                "covered_functions": int(values["FNH"]),
                "num_functions": int(values["FNF"]),
                "missing": ranges(uncovered),
            }
        )
    if suite.files:
        suite.coverage = {
            key: sum(row[key] for row in suite.files)
            for key in (*COVERAGE_KEYS, "covered_functions", "num_functions")
        }


def ranges(numbers):
    spans = []
    for number in sorted(set(numbers)):
        if spans and spans[-1][1] == number - 1:
            spans[-1][1] = number
        else:
            spans.append([number, number])
    return ", ".join(str(start) if start == end else f"{start}–{end}" for start, end in spans)


def number(value):
    return f"{value:,}".replace(",", ".")


def rate(hit, total):
    return f"{100 * hit / total:.2f}%".replace(".", ",") if total else "—"


def counts(hit, total):
    return f"{number(hit)}/{number(total)}"


def metric(label, value, note=""):
    detail = f"<small>{escape(note)}</small>" if note else ""
    return f'<div class="metric"><dt>{escape(label)}</dt><dd>{escape(value)}{detail}</dd></div>'


def summarize(section_id, title, description, suite):
    kpis = []
    if cases := suite.cases:
        kpis.extend(
            [
                metric("Testes aprovados", counts(cases["passed"], cases["total"])),
                metric("Falhas", number(cases["failed"])),
                metric("Pulados", number(cases["skipped"])),
                metric("Duração", f"{cases['time']:.2f} s".replace(".", ",")),
            ]
        )
    if stats := suite.coverage:
        covered, lines = stats["covered_lines"], stats["num_statements"]
        branches, total_branches = stats["covered_branches"], stats["num_branches"]
        kpis.extend(
            [
                metric("Linhas cobertas", rate(covered, lines), counts(covered, lines)),
                metric(
                    "Ramificações cobertas",
                    rate(branches, total_branches),
                    counts(branches, total_branches),
                ),
                metric("Arquivos medidos", number(len(suite.files))),
                metric("Linhas a cobrir", number(lines - covered)),
            ]
        )
        if "num_functions" in stats:
            hit, total = stats["covered_functions"], stats["num_functions"]
            kpis.append(metric("Funções cobertas", rate(hit, total), counts(hit, total)))
    errors = "".join(f"<p><strong>{escape(error)}</strong></p>" for error in suite.errors)
    notes = ""
    if suite.notes:
        items = "".join(f"<li>{escape(note)}</li>" for note in suite.notes)
        notes = f"<details><summary>Testes pulados ou com falha</summary><ul>{items}</ul></details>"
    details = detail_table(suite.files, title, section_id == "backend") if suite.files else ""
    indicators = f'<dl class="metrics">{"".join(kpis)}</dl>' if kpis else ""
    return f'''<section id="{section_id}" aria-labelledby="{section_id}-title">
      <h2 id="{section_id}-title">{escape(title)}</h2>
      <p class="muted">{description}</p>
      {errors}{indicators}{notes}{details}
    </section>'''


def detail_table(files, scope, is_full):
    rows = sorted(
        files,
        key=lambda row: (
            row["covered_lines"] - row["num_statements"],
            row["covered_branches"] - row["num_branches"],
            row["name"],
        ),
    )
    rendered = []
    for row in rows:
        lines, branches = row["num_statements"], row["num_branches"]
        missed = lines - row["covered_lines"]
        name = escape(row["name"])
        missing = escape(row["missing"])
        missing_content = (
            f'<details class="lines"><summary>{number(missed)} linhas</summary><p>{missing}</p></details>'
            if missed
            else "—"
        )
        rendered.append(f"""<tr>
          <th scope="row"><code>{name}</code></th>
          <td>{rate(row["covered_lines"], lines)}<small>{counts(row["covered_lines"], lines) if lines else ""}</small></td>
          <td>{rate(row["covered_branches"], branches)}<small>{counts(row["covered_branches"], branches) if branches else ""}</small></td>
          <td>{missing_content}</td>
        </tr>""")
    return f'''<details class="files"{" open" if not is_full else ""}>
      <summary>Cobertura por arquivo <span>({number(len(rows))})</span></summary>
      <div class="table-scroll">
        <table aria-label="Cobertura por arquivo — {escape(scope)}">
          <thead><tr><th scope="col">Arquivo</th><th scope="col">Linhas</th><th scope="col">Ramificações</th><th scope="col">Linhas a cobrir</th></tr></thead>
          <tbody>{"".join(rendered)}</tbody>
        </table>
      </div>
    </details>'''


def render(full, unit, web, status, generated):
    frontend_count = sum(
        path.suffix in {".js", ".jsx"} for path in (FRONTEND / "src").rglob("*") if path.is_file()
    )
    sections = [
        summarize(
            "unitarios-backend",
            "Backend · testes unitários",
            "Contexto analítico, data local e contrato de anotações, com casos em "
            "<code>backend/tests/test_analytical_context.py</code>, <code>backend/tests/test_period.py</code> e <code>backend/tests/test_annotation_contract.py</code>.",
            unit,
        ),
        summarize(
            "unitarios-frontend",
            "Frontend · testes unitários",
            f"{len(web.files)} de {frontend_count} arquivos JavaScript/JSX em <code>frontend/src</code> foram medidos. "
            "O Node.js mede os módulos carregados pelos testes em <code>frontend/tests/unit/</code>.",
            web,
        ),
        summarize(
            "backend",
            "Backend · suíte completa",
            "Testes unitários e de integração. Cobertura de <code>backend/src</code>, com migrações excluídas.",
            full,
        ),
    ]
    styles = """
      :root { color-scheme: light; font-family: system-ui, sans-serif; color: #14293c; background: #f3f6f8; line-height: 1.55; }
      * { box-sizing: border-box; }
      body { margin: 0; }
      header { background: #14334a; color: #fff; }
      .wrap, main { max-width: 1120px; margin: auto; padding-inline: clamp(16px,4vw,52px); }
      header .wrap { padding-block: 44px 34px; }
      h1 { margin: 4px 0 10px; font-size: clamp(2rem,5vw,3.25rem); line-height: 1.1; letter-spacing: -.04em; }
      .brand { margin: 0; color: #c0e9de; font-weight: 700; }
      header p:last-child { margin: 0; color: #dce9f1; }
      nav { padding-block: 20px 10px; display: flex; flex-wrap: wrap; gap: 10px 18px; }
      nav a { color: #07594e; font-weight: 650; text-underline-offset: 3px; }
      section { margin: 18px 0; padding: clamp(14px,3vw,28px); background: #fff; border: 1px solid #d9e3e9; border-radius: 12px; scroll-margin-top: 12px; }
      h2 { font-size: clamp(1.25rem,3vw,1.65rem); margin: 0 0 4px; line-height: 1.3; }
      .muted { overflow-wrap: anywhere; color: #405a6d; margin: 0; }
      .metrics { display: grid; grid-template-columns: repeat(auto-fit,minmax(126px,1fr)); gap: 8px; margin: 20px 0; }
      .metric { padding: 10px 11px; border: 1px solid #d9e8e5; background: #f3faf8; border-radius: 8px; }
      dt { font-size: .83rem; color: #304d56; }
      dd { margin: 1px 0 0; color: #07594e; font-weight: 700; font-size: 1.32rem; }
      small { display: block; font-size: .79rem; font-weight: 500; color: #405a6d; }
      dd, td { font-variant-numeric: tabular-nums; }
      summary { cursor: pointer; color: #07594e; font-weight: 650; }
      summary span { color: #405a6d; }
      .table-scroll { margin-top: 10px; overflow-x: auto; }
      table { border-collapse: collapse; width: 100%; text-align: left; font-size: .9rem; }
      th, td { padding: 9px 10px; border-bottom: 1px solid #e1e9ee; vertical-align: top; }
      thead { background: #e9f1f5; }
      tbody th { font-weight: 500; overflow-wrap: anywhere; width: 53%; }
      tbody tr:nth-child(even) { background: #f8fbfc; }
      .lines p { margin: 4px 0; overflow-wrap: anywhere; }
      code { font-family: ui-monospace, Consolas, monospace; font-size: .9em; }
      #metodo { margin-bottom: 32px; }
      #metodo p { margin: 8px 0; }
      @media (max-width: 560px) {
        table { min-width: 510px; }
        header .wrap { padding-block: 28px 24px; }
      }
    """
    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DatumLex · Cobertura de testes</title>
<style>{styles}</style>
</head>
<body>
<header><div class="wrap">
  <p class="brand">DatumLex</p>
  <h1>Cobertura de testes</h1>
  <p>Gerado em <time datetime="{generated.isoformat()}">{generated:%d/%m/%Y às %H:%M:%S %z}</time> · {status}</p>
</div></header>
<main>
  <nav aria-label="Seções do relatório">
    <a href="#unitarios-backend">Backend unitário</a>
    <a href="#unitarios-frontend">Frontend unitário</a>
    <a href="#backend">Backend completo</a>
    <a href="#metodo">Como foi medido</a>
  </nav>
  {"".join(sections)}
  <section id="metodo" aria-labelledby="metodo-title">
    <h2 id="metodo-title">Como foi medido</h2>
    <p>O backend foi medido com pytest e Coverage.py em SQLite em memória. O frontend foi medido com <code>node:test</code> e a cobertura nativa do Node.js, sem executar a suíte Playwright.</p>
    <p>Os testes do recorte unitário do backend também estão na suíte completa. Os resultados dos recortes têm denominadores próprios e os totais de testes do backend se sobrepõem.</p>
    <p>A duração é a registrada por cada executor durante a medição. Uma falha de execução ou de coleta de cobertura é indicada no escopo correspondente.</p>
  </section>
</main>
</body>
</html>
"""
    return html


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".test-report-", dir=OUTPUT.parent) as temporary:
        directory = Path(temporary)
        unit_dir, full_dir = directory / "python-unit", directory / "python-full"
        unit_dir.mkdir()
        full_dir.mkdir()
        unit = backend_run(
            unit_dir,
            "Backend · testes unitários",
            ["--include=src/services/analytical_context.py,src/services/period.py,src/nlp/contracts.py"],
            ["tests/test_analytical_context.py", "tests/test_period.py", "tests/test_annotation_contract.py"],
        )
        full = backend_run(
            full_dir,
            "Backend · suíte completa",
            ["--source=src", "--omit=*/migrations/*"],
            [],
        )
        web = frontend_run(directory)
        unsuccessful = any(
            suite.errors or (suite.cases and suite.cases["failed"]) for suite in (unit, full, web)
        )
        status = "Execução com falhas ou resultados incompletos" if unsuccessful else "Execução concluída"
        fresh_report = directory / OUTPUT.name
        fresh_report.write_text(
            render(full, unit, web, status, datetime.now().astimezone()),
            encoding="utf-8",
        )
        fresh_report.replace(OUTPUT)
    print(f"\nRelatório: {OUTPUT}")
    return int(unsuccessful)


if __name__ == "__main__":
    sys.exit(main())
