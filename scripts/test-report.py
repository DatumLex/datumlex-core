"""Run the DatumLex test suites, generate SonarQube artifacts, and write HTML coverage dashboards."""

import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
TOOLS = ROOT / "tools"
OUTPUT = ROOT / "output" / "coverage" / "index.html"
TESTS_HTML_OUTPUT = BACKEND / "tests" / "relatorio-cobertura.html"
SONAR_COVERAGE_XML = OUTPUT.parent / "backend-coverage.xml"
SONAR_JUNIT_XML = OUTPUT.parent / "backend-junit.xml"
SONAR_FRONTEND_LCOV = OUTPUT.parent / "frontend-lcov.info"
COVERAGE_KEYS = ("covered_lines", "num_statements", "covered_branches", "num_branches")

LAYER_DEFINITIONS = (
    ("backend/src/services/", "Serviços de Domínio e IA", "Pesquisa jurídica, Gemini AI, NLP v2, métricas e catálogo"),
    ("backend/src/routes/", "Rotas REST / API", "Endpoints HTTP de pesquisa, estatísticas, NLP v2, chat e exportação"),
    ("backend/src/nlp/", "Motor NLP v2 e Contratos", "Extração, validação de contratos, tópicos e evidências literais"),
    ("backend/src/etl/", "Pipeline ETL", "Transformação, classificação de desfechos TPU, amostragem e carga"),
    ("backend/src/api/", "Clientes Externos", "Integrações oficiais DataJud/CNJ, Pangea BNP e fontes jurídicas"),
    ("backend/src/accounts/", "Segurança e Contas", "Autenticação, controle de acesso por tribunal, sessões e auditoria"),
    ("backend/src/db/", "Modelos e Persistência", "Esquema relacional, coortes e comandos operacionais Django"),
    ("frontend/src/", "Frontend React / Vite", "Utilitários de UI, API gateway, rotas de deploy e apresentação"),
)


@dataclass
class Suite:
    cases: dict | None = None
    coverage: dict | None = None
    files: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class StaticAnalysis:
    ruff_critical: int | None = None
    ruff_style: int | None = None
    ruff_top_rules: list[tuple[str, int]] = field(default_factory=list)
    ruff_note: str = ""
    eslint_errors: int | None = None
    eslint_warnings: int | None = None
    eslint_files: int = 0
    eslint_note: str = ""


def run(command, cwd, env=None):
    try:
        return subprocess.run(command, cwd=cwd, env=env, check=False).returncode
    except OSError as error:
        print(error, file=sys.stderr)
        return 1


def run_capture(command, cwd, env=None):
    try:
        return subprocess.run(command, cwd=cwd, env=env, check=False, capture_output=True, text=True)
    except OSError as error:
        return subprocess.CompletedProcess(command, 1, "", str(error))


def backend_python():
    path = BACKEND / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(path) if path.is_file() else sys.executable


def backend_run(directory, title, coverage_args, tests, export_sonar=False):
    print(f"\n{title}", flush=True)
    env = os.environ.copy()
    env.update(COVERAGE_FILE=str(directory / ".coverage"), PYTHON_DOTENV_DISABLED="1")
    xml_file = directory / "pytest.xml"
    json_file = directory / "coverage.json"
    cobertura_file = directory / "coverage.xml"
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
        if export_sonar:
            shutil.copyfile(xml_file, SONAR_JUNIT_XML)
    else:
        suite.errors.append("O pytest não gerou resultados. Confira as dependências em requirements-dev.txt.")
    if not (directory / ".coverage").is_file() or run(
        [*coverage, "json", "-o", str(json_file)], BACKEND, env
    ):
        suite.errors.append("A cobertura Python não pôde ser coletada.")
    else:
        read_python_coverage(json_file, suite)
        if export_sonar and run([*coverage, "xml", "-o", str(cobertura_file)], BACKEND, env) == 0:
            normalize_cobertura_xml(cobertura_file, SONAR_COVERAGE_XML)
    return suite


def normalize_cobertura_xml(src_xml, dst_xml):
    """Ensure Cobertura XML paths resolve from repository root (backend/src/...) for SonarQube."""
    tree = ET.parse(src_xml)
    root = tree.getroot()
    for source in root.findall(".//sources/source"):
        source.text = str(ROOT)
    for cls in root.findall(".//class"):
        fname = (cls.get("filename") or "").replace("\\", "/")
        if fname and not fname.startswith("backend/"):
            cls.set("filename", f"backend/{fname}")
    tree.write(dst_xml, encoding="utf-8", xml_declaration=True)


def tools_run(directory):
    print("\nFerramentas · validação NLP e coletores", flush=True)
    xml_file = directory / "tools-pytest.xml"
    env = os.environ.copy()
    env.update(PYTHON_DOTENV_DISABLED="1")
    status = run(
        [
            backend_python(),
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            "-rs",
            "--junitxml",
            str(xml_file),
            "tools",
        ],
        ROOT,
        env,
    )
    suite = Suite()
    if status:
        suite.errors.append(f"Os testes de ferramentas retornaram código {status}.")
    if xml_file.is_file():
        read_pytest(xml_file, suite)
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
        normalized_lcov = re.sub(
            r"^SF:(?!frontend/)",
            "SF:frontend/",
            lcov_file.read_text(encoding="utf-8").replace("\\", "/"),
            flags=re.MULTILINE,
        )
        SONAR_FRONTEND_LCOV.write_text(normalized_lcov, encoding="utf-8")
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


def run_static_analysis():
    print("\nAnálise estática · Ruff (Python) + ESLint (Frontend)", flush=True)
    report = StaticAnalysis()

    ruff = run_capture([backend_python(), "-m", "ruff", "check", "src", "--output-format=json"], BACKEND)
    try:
        issues = json.loads(ruff.stdout or "[]")
        if isinstance(issues, list):
            critical = [i for i in issues if str(i.get("code", "")).startswith(("F", "E9"))]
            style = [i for i in issues if not str(i.get("code", "")).startswith(("F", "E9"))]
            report.ruff_critical = len(critical)
            report.ruff_style = len(style)
            report.ruff_top_rules = Counter(i.get("code", "?") for i in issues).most_common(6)
    except json.JSONDecodeError:
        report.ruff_note = "Ruff indisponível neste ambiente."

    eslint_bin = FRONTEND / "node_modules" / ".bin" / ("eslint.cmd" if os.name == "nt" else "eslint")
    if eslint_bin.is_file():
        eslint = run_capture([str(eslint_bin), ".", "--format=json"], FRONTEND)
        try:
            es_files = json.loads(eslint.stdout or "[]")
            if isinstance(es_files, list):
                report.eslint_files = len(es_files)
                report.eslint_errors = sum(f.get("errorCount", 0) for f in es_files)
                report.eslint_warnings = sum(f.get("warningCount", 0) for f in es_files)
        except json.JSONDecodeError:
            report.eslint_note = "Não foi possível interpretar a saída do ESLint."
    else:
        report.eslint_note = "ESLint não instalado em frontend/node_modules neste ambiente."

    return report


def group_by_layer(full_files, web_files):
    all_files = [*full_files, *web_files]
    layers = []
    matched = set()
    for prefix, title, subtitle in LAYER_DEFINITIONS:
        bucket = [row for row in all_files if row["name"].startswith(prefix)]
        if not bucket:
            continue
        matched.update(row["name"] for row in bucket)
        covered = sum(row["covered_lines"] for row in bucket)
        total = sum(row["num_statements"] for row in bucket)
        br_cov = sum(row["covered_branches"] for row in bucket)
        br_tot = sum(row["num_branches"] for row in bucket)
        pct = (100 * covered / total) if total else 0.0
        layers.append(
            {
                "prefix": prefix,
                "title": title,
                "subtitle": subtitle,
                "files": len(bucket),
                "covered_lines": covered,
                "num_statements": total,
                "covered_branches": br_cov,
                "num_branches": br_tot,
                "pct": pct,
            }
        )
    other = [row for row in all_files if row["name"] not in matched and row["num_statements"] > 0]
    if other:
        covered = sum(row["covered_lines"] for row in other)
        total = sum(row["num_statements"] for row in other)
        br_cov = sum(row["covered_branches"] for row in other)
        br_tot = sum(row["num_branches"] for row in other)
        layers.append(
            {
                "prefix": "outros",
                "title": "Outros Módulos",
                "subtitle": "Arquivos auxiliares medidos na execução",
                "files": len(other),
                "covered_lines": covered,
                "num_statements": total,
                "covered_branches": br_cov,
                "num_branches": br_tot,
                "pct": (100 * covered / total) if total else 0.0,
            }
        )
    return layers


def ranges(numbers):
    spans = []
    for n in sorted(set(numbers)):
        if spans and spans[-1][1] == n - 1:
            spans[-1][1] = n
        else:
            spans.append([n, n])
    return ", ".join(str(start) if start == end else f"{start}–{end}" for start, end in spans)


def number(value):
    return f"{value:,}".replace(",", ".")


def rate(hit, total):
    return f"{100 * hit / total:.2f}%".replace(".", ",") if total else "—"


def counts(hit, total):
    return f"{number(hit)}/{number(total)}"


def tone(pct):
    if pct >= 80:
        return "good"
    if pct >= 60:
        return "warn"
    return "low"


def metric(label, value, note="", badge_tone=""):
    detail = f"<small>{escape(note)}</small>" if note else ""
    extra = f" metric--{badge_tone}" if badge_tone else ""
    return f'<div class="metric{extra}"><dt>{escape(label)}</dt><dd>{escape(value)}{detail}</dd></div>'


def summarize(section_id, title, description, suite):
    kpis = []
    if cases := suite.cases:
        kpis.extend(
            [
                metric("Testes aprovados", counts(cases["passed"], cases["total"]), badge_tone="good" if not cases["failed"] else "low"),
                metric("Falhas", number(cases["failed"]), badge_tone="good" if not cases["failed"] else "low"),
                metric("Pulados", number(cases["skipped"])),
                metric("Duração", f"{cases['time']:.2f} s".replace(".", ",")),
            ]
        )
    if stats := suite.coverage:
        covered, lines = stats["covered_lines"], stats["num_statements"]
        branches, total_branches = stats["covered_branches"], stats["num_branches"]
        line_pct = (100 * covered / lines) if lines else 0.0
        kpis.extend(
            [
                metric("Linhas cobertas", rate(covered, lines), counts(covered, lines), badge_tone=tone(line_pct)),
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
    errors = "".join(f"<p class='alert'><strong>{escape(error)}</strong></p>" for error in suite.errors)
    notes = ""
    if suite.notes:
        items = "".join(f"<li>{escape(note)}</li>" for note in suite.notes)
        notes = f"<details><summary>Testes pulados ou com falha ({len(suite.notes)})</summary><ul>{items}</ul></details>"
    details = detail_table(suite.files, title, section_id) if suite.files else ""
    indicators = f'<dl class="metrics">{"".join(kpis)}</dl>' if kpis else ""
    return f'''<section id="{section_id}" aria-labelledby="{section_id}-title">
      <h2 id="{section_id}-title">{escape(title)}</h2>
      <p class="muted">{description}</p>
      {errors}{indicators}{notes}{details}
    </section>'''


def detail_table(files, scope, section_id):
    rows = sorted(
        files,
        key=lambda row: (
            -(100 * row["covered_lines"] / row["num_statements"]) if row["num_statements"] else -101.0,
            row["name"],
        ),
    )
    rendered = []
    for row in rows:
        lines, branches = row["num_statements"], row["num_branches"]
        missed = lines - row["covered_lines"]
        pct = (100 * row["covered_lines"] / lines) if lines else 100.0
        br_pct = (100 * row["covered_branches"] / branches) if branches else -1.0
        name = escape(row["name"])
        missing = escape(row["missing"])
        missing_content = (
            f'<details class="lines"><summary>{number(missed)} linha(s)</summary><p>{missing}</p></details>'
            if missed
            else "0"
        )
        rendered.append(
            f'<tr data-file="{name.lower()}" data-pct="{pct:.4f}" data-br="{br_pct:.4f}" '
            f'data-lines="{lines}" data-missed="{missed}">'
            f'<td class="col-file"><code>{name}</code></td>'
            f'<td class="num"><strong>{rate(row["covered_lines"], lines)}</strong></td>'
            f'<td class="num">{counts(row["covered_lines"], lines) if lines else "0/0"}</td>'
            f'<td class="num">{rate(row["covered_branches"], branches)}</td>'
            f'<td class="num">{counts(row["covered_branches"], branches) if branches else "—"}</td>'
            f'<td>{missing_content}</td>'
            f'</tr>'
        )
    search_box = (
        f'<div class="toolbar">'
        f'<label>Filtrar arquivo: <input type="search" placeholder="Ex.: research, nlp, legal_chat, accounts..." '
        f'oninput="filterTable(this, \'{section_id}-tbody\')"></label>'
        f'<span class="hint">Clique nos cabeçalhos para ordenar · {number(len(rows))} arquivo(s)</span>'
        f'</div>'
        if len(rows) > 5
        else ""
    )
    return f'''<details class="files" open>
      <summary>Cobertura por arquivo — % individual <span>({number(len(rows))} arquivos)</span></summary>
      {search_box}
      <div class="table-scroll">
        <table aria-label="Cobertura por arquivo — {escape(scope)}">
          <thead>
            <tr>
              <th scope="col" class="sortable" onclick="sortTable('{section_id}-tbody', 'file', this)">Arquivo</th>
              <th scope="col" class="num sortable" onclick="sortTable('{section_id}-tbody', 'pct', this)">Linhas (%)</th>
              <th scope="col" class="num sortable" onclick="sortTable('{section_id}-tbody', 'lines', this)">Cobertas / Total</th>
              <th scope="col" class="num sortable" onclick="sortTable('{section_id}-tbody', 'br', this)">Ramificações (%)</th>
              <th scope="col" class="num">Ramos</th>
              <th scope="col" class="sortable" onclick="sortTable('{section_id}-tbody', 'missed', this)">Linhas descobertas</th>
            </tr>
          </thead>
          <tbody id="{section_id}-tbody">{"".join(rendered)}</tbody>
        </table>
      </div>
    </details>'''


def render_layers_section(layers):
    rows = []
    for layer in layers:
        pct_str = rate(layer["covered_lines"], layer["num_statements"])
        br_str = rate(layer["covered_branches"], layer["num_branches"])
        rows.append(
            f'<tr>'
            f'<td><strong>{escape(layer["title"])}</strong><br><small>{escape(layer["subtitle"])}</small></td>'
            f'<td><code>{escape(layer["prefix"])}</code></td>'
            f'<td class="num">{number(layer["files"])}</td>'
            f'<td class="num"><strong>{pct_str}</strong></td>'
            f'<td class="num">{counts(layer["covered_lines"], layer["num_statements"])}</td>'
            f'<td class="num">{br_str}</td>'
            f'<td class="num">{counts(layer["covered_branches"], layer["num_branches"])}</td>'
            f'</tr>'
        )
    return f'''<section id="camadas" aria-labelledby="camadas-title">
      <h2 id="camadas-title">Cobertura por camada e serviço</h2>
      <p class="muted">Agrupamento da cobertura medida por pacote/serviço (backend e frontend).</p>
      <div class="table-scroll">
        <table aria-label="Cobertura por camada e serviço">
          <thead>
            <tr>
              <th scope="col">Camada / Serviço</th>
              <th scope="col">Diretório</th>
              <th scope="col" class="num">Arquivos</th>
              <th scope="col" class="num">Linhas (%)</th>
              <th scope="col" class="num">Linhas</th>
              <th scope="col" class="num">Ramificações (%)</th>
              <th scope="col" class="num">Ramos</th>
            </tr>
          </thead>
          <tbody>{"".join(rows)}</tbody>
        </table>
      </div>
    </section>'''


def render_sonar_section(static, sonar_files_status):
    ruff_crit = "—" if static.ruff_critical is None else number(static.ruff_critical)
    ruff_style = "—" if static.ruff_style is None else number(static.ruff_style)
    es_err = "—" if static.eslint_errors is None else number(static.eslint_errors)
    es_warn = "—" if static.eslint_warnings is None else number(static.eslint_warnings)

    kpis = [
        metric("Ruff · Erros críticos (F/E9)", ruff_crit, static.ruff_note or "Bugs, nomes indefinidos e imports mortos"),
        metric("Ruff · Avisos de estilo", ruff_style, "Avisos de formatação em backend/src"),
        metric("ESLint · Erros Frontend", es_err, static.eslint_note or f"{number(static.eslint_files)} arquivos verificados"),
        metric("ESLint · Avisos Frontend", es_warn, "Regras React Hooks e JS"),
    ]
    artifact_rows = "".join(
        f"<tr><td><code>{escape(name)}</code></td><td>{escape(desc)}</td>"
        f"<td><strong>{'OK' if exists else 'Pendente'}</strong></td></tr>"
        for name, desc, exists in sonar_files_status
    )
    rules_note = ""
    if static.ruff_top_rules:
        chips = ", ".join(f"{code} ({n})" for code, n in static.ruff_top_rules)
        rules_note = f"<p class='muted' style='margin-top:8px'>Regras Ruff (estilo): <code>{escape(chips)}</code></p>"

    return f'''<section id="sonar" aria-labelledby="sonar-title">
      <h2 id="sonar-title">Análise estática e integração SonarQube</h2>
      <p class="muted">Projeto SonarQube <code>br.edu.fatec:datumlex</code> (Python + JS/JSX) com relatórios gerados automaticamente.</p>
      <dl class="metrics">{"".join(kpis)}</dl>
      {rules_note}
      <div class="table-scroll">
        <table aria-label="Artefatos SonarQube">
          <thead><tr><th scope="col">Artefato / Configuração</th><th scope="col">Finalidade</th><th scope="col">Status</th></tr></thead>
          <tbody>{artifact_rows}</tbody>
        </table>
      </div>
      <p class="muted" style="margin-top:10px">
        Local (Docker): <code>docker compose -f docker-compose.sonar.yml up -d sonarqube</code> e
        <code>SONAR_TOKEN=&lt;token&gt; docker compose -f docker-compose.sonar.yml run --rm sonar-scanner</code>.
        CI: <code>.github/workflows/sonar.yml</code> (secrets <code>SONAR_TOKEN</code> e <code>SONAR_HOST_URL</code>).
      </p>
    </section>'''


def render(full, unit, web, tools, static, status, generated, unsuccessful):
    frontend_count = sum(
        path.suffix in {".js", ".jsx"} for path in (FRONTEND / "src").rglob("*") if path.is_file()
    )
    layers = group_by_layer(full.files, web.files)
    total_tests = sum(
        (s.cases or {}).get("total", 0) for s in (full, web, tools)
    )
    total_passed = sum(
        (s.cases or {}).get("passed", 0) for s in (full, web, tools)
    )
    total_failed = sum(
        (s.cases or {}).get("failed", 0) for s in (full, web, tools)
    )
    total_skipped = sum(
        (s.cases or {}).get("skipped", 0) for s in (full, web, tools)
    )
    backend_line_pct = (
        100 * full.coverage["covered_lines"] / full.coverage["num_statements"]
        if full.coverage and full.coverage["num_statements"]
        else 0.0
    )
    frontend_line_pct = (
        100 * web.coverage["covered_lines"] / web.coverage["num_statements"]
        if web.coverage and web.coverage["num_statements"]
        else 0.0
    )
    gate_ok = not unsuccessful and (static.ruff_critical in (0, None)) and (static.eslint_errors in (0, None))

    sonar_files_status = [
        ("sonar-project.properties", "Configuração unificada SonarQube (Python + JS/JSX, sem segredos hardcoded)", (ROOT / "sonar-project.properties").is_file()),
        (".github/workflows/sonar.yml", "Pipeline CI de cobertura, lint e envio ao SonarQube/SonarCloud", (ROOT / ".github/workflows/sonar.yml").is_file()),
        ("docker-compose.sonar.yml", "Stack local reproduzível SonarQube Community + sonar-scanner", (ROOT / "docker-compose.sonar.yml").is_file()),
        ("output/coverage/backend-coverage.xml", "Relatório Cobertura XML importado por sonar.python.coverage.reportPaths", SONAR_COVERAGE_XML.is_file()),
        ("output/coverage/backend-junit.xml", "Relatório JUnit XML importado por sonar.python.xunit.reportPath", SONAR_JUNIT_XML.is_file()),
        ("output/coverage/frontend-lcov.info", "Relatório LCOV importado por sonar.javascript.lcov.reportPaths", SONAR_FRONTEND_LCOV.is_file()),
    ]

    summary_kpis = [
        metric(
            "Quality Gate",
            "APROVADO" if gate_ok else "ATENÇÃO",
            "Zero falhas e zero erros críticos" if gate_ok else "Verifique falhas ou erros críticos abaixo",
            badge_tone="good" if gate_ok else "low",
        ),
        metric(
            "Testes Automatizados",
            counts(total_passed, total_tests),
            f"{number(total_failed)} falha(s) · {number(total_skipped)} pulado(s)",
            badge_tone="good" if total_failed == 0 else "low",
        ),
        metric(
            "Cobertura Backend (src)",
            rate(full.coverage["covered_lines"], full.coverage["num_statements"]) if full.coverage else "—",
            counts(full.coverage["covered_lines"], full.coverage["num_statements"]) if full.coverage else "",
            badge_tone=tone(backend_line_pct),
        ),
        metric(
            "Cobertura Frontend (unit)",
            rate(web.coverage["covered_lines"], web.coverage["num_statements"]) if web.coverage else "—",
            f"{len(web.files)} módulos testados de {frontend_count}",
            badge_tone=tone(frontend_line_pct),
        ),
        metric(
            "Ruff + ESLint (Críticos)",
            number((static.ruff_critical or 0) + (static.eslint_errors or 0)),
            "Erros críticos Python + JS/JSX",
            badge_tone="good" if (static.ruff_critical or 0) + (static.eslint_errors or 0) == 0 else "low",
        ),
        metric(
            "SonarQube Ready",
            f"{sum(1 for _, _, ok in sonar_files_status if ok)}/{len(sonar_files_status)}",
            "Artefatos XML/LCOV e workflow prontos",
            badge_tone="good",
        ),
    ]

    executive_section = f'''<section id="resumo" aria-labelledby="resumo-title">
      <h2 id="resumo-title">Resumo Executivo · Quality Gate</h2>
      <p class="muted">Visão consolidada da automação de testes do DatumLex (Backend Django + Frontend React + Ferramentas NLP) com saída pronta para SonarQube.</p>
      <dl class="metrics">{"".join(summary_kpis)}</dl>
    </section>'''

    sections = [
        executive_section,
        render_layers_section(layers),
        summarize(
            "backend",
            "Cobertura por arquivo (%) — Backend completo",
            "47 arquivos de teste exercitando APIs REST, serviços de domínio, Chat Gemini, NLP v2, ETL DataJud/Pangea, segurança e settings de produção. Cobertura de <code>backend/src</code> sem migrações.",
            full,
        ),
        summarize(
            "unitarios-frontend",
            "Frontend · testes unitários (Node.js) — % por arquivo",
            f"{len(web.files)} de {frontend_count} arquivos JavaScript/JSX em <code>frontend/src</code> foram medidos. "
            "O Node.js mede os módulos carregados pelos testes em <code>frontend/tests/unit/</code>.",
            web,
        ),
        render_sonar_section(static, sonar_files_status),
        summarize(
            "unitarios-backend",
            "Backend · testes unitários (recorte rápido)",
            "Contexto analítico, data local e contrato de anotações, com casos em "
            "<code>backend/tests/test_analytical_context.py</code>, <code>backend/tests/test_period.py</code> e <code>backend/tests/test_annotation_contract.py</code>.",
            unit,
        ),
        summarize(
            "ferramentas",
            "Ferramentas · validação NLP e coletores",
            "Testes automatizados em <code>tools/doctrine/</code> e <code>tools/nlp_validation/</code> garantindo contratos de coleta e cobertura.",
            tools,
        ),
    ]
    styles = """
      :root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; color: #111; background: #fff; line-height: 1.45; font-size: 14px; }
      * { box-sizing: border-box; }
      body { margin: 0; padding: 0; }
      header { border-bottom: 2px solid #111; background: #fff; }
      .wrap, main { max-width: 1160px; margin: 0 auto; padding: 0 20px; }
      header .wrap { padding: 18px 20px 14px; display: flex; flex-wrap: wrap; justify-content: space-between; align-items: baseline; gap: 12px; }
      h1 { margin: 2px 0 4px; font-size: 1.55rem; font-weight: 700; color: #111; }
      .brand { margin: 0; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .8rem; text-transform: uppercase; letter-spacing: .04em; color: #555; }
      header p:last-child { margin: 0; font-size: .86rem; color: #444; }
      .gate-badge { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .85rem; font-weight: 700; padding: 4px 10px; border: 1px solid #111; background: #f8f8f8; color: #111; }
      .gate-badge--low { border-color: #991b1b; color: #991b1b; background: #fff5f5; }
      nav { padding: 10px 0; border-bottom: 1px solid #d4d4d4; display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: .88rem; }
      nav a { color: #0b4f8a; text-decoration: underline; }
      section { margin: 0; padding: 18px 0; border-bottom: 1px solid #e0e0e0; scroll-margin-top: 8px; }
      h2 { font-size: 1.15rem; margin: 0 0 4px; font-weight: 700; color: #111; }
      .muted { overflow-wrap: anywhere; color: #555; margin: 0 0 10px; font-size: .88rem; }
      .alert { color: #991b1b; border: 1px solid #991b1b; background: #fff5f5; padding: 8px 10px; }
      .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0; margin: 10px 0; border-top: 1px solid #ccc; border-left: 1px solid #ccc; }
      .metric { padding: 8px 10px; border-right: 1px solid #ccc; border-bottom: 1px solid #ccc; background: #fafafa; }
      .metric--low { background: #fff5f5; }
      dt { font-size: .78rem; color: #555; }
      dd { margin: 2px 0 0; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-weight: 700; font-size: 1.15rem; color: #111; }
      .metric--low dd { color: #991b1b; }
      small { display: block; font-family: inherit; font-size: .76rem; font-weight: 400; color: #555; }
      dd, td { font-variant-numeric: tabular-nums; }
      summary { cursor: pointer; font-weight: 700; color: #111; margin: 8px 0 6px; }
      summary span { color: #555; font-weight: 400; }
      .toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; margin: 8px 0; font-size: .86rem; }
      .toolbar input { padding: 4px 8px; border: 1px solid #999; min-width: 260px; font: inherit; }
      .hint { color: #666; font-size: .8rem; }
      .table-scroll { margin-top: 6px; overflow-x: auto; }
      table { border-collapse: collapse; width: 100%; text-align: left; font-size: .85rem; border: 1px solid #ccc; }
      th, td { padding: 6px 8px; border: 1px solid #ddd; vertical-align: top; }
      thead th { background: #efefef; font-weight: 700; color: #111; white-space: nowrap; }
      th.sortable { cursor: pointer; user-select: none; }
      th.sortable:hover { background: #e3e3e3; }
      th.sortable::after { content: " ↕"; color: #777; font-weight: 400; }
      tbody tr:nth-child(even) { background: #fafafa; }
      td.num, th.num { text-align: right; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; white-space: nowrap; }
      td.col-file { overflow-wrap: anywhere; }
      .lines summary { margin: 0; font-weight: 400; color: #0b4f8a; }
      .lines p { margin: 4px 0 0; overflow-wrap: anywhere; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .8rem; color: #444; }
      code { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .88em; }
      #metodo { border-bottom: 0; padding-bottom: 32px; }
      #metodo p { margin: 6px 0; color: #333; }
      @media (max-width: 560px) {
        table { min-width: 560px; }
      }
    """
    script = """
      function filterTable(input, tbodyId) {
        var q = (input.value || '').trim().toLowerCase();
        var rows = document.getElementById(tbodyId).querySelectorAll('tr');
        rows.forEach(function (tr) {
          var name = tr.getAttribute('data-file') || '';
          tr.style.display = !q || name.indexOf(q) !== -1 ? '' : 'none';
        });
      }
      function sortTable(tbodyId, field, th) {
        var tbody = document.getElementById(tbodyId);
        var asc = th.getAttribute('data-asc') !== '1';
        th.setAttribute('data-asc', asc ? '1' : '0');
        var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
        rows.sort(function (a, b) {
          var av = a.getAttribute('data-' + field) || '';
          var bv = b.getAttribute('data-' + field) || '';
          if (field === 'file') return asc ? av.localeCompare(bv) : bv.localeCompare(av);
          var an = parseFloat(av), bn = parseFloat(bv);
          return asc ? (an - bn) : (bn - an);
        });
        rows.forEach(function (r) { tbody.appendChild(r); });
      }
    """
    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DatumLex — Relatório de Testes Automatizados e Cobertura</title>
<style>{styles}</style>
</head>
<body>
<header><div class="wrap">
  <div>
    <p class="brand">DatumLex / Qualidade e Testes Automatizados</p>
    <h1>Relatório de Testes, Cobertura por Arquivo e SonarQube</h1>
    <p>Gerado em <time datetime="{generated.isoformat()}">{generated:%d/%m/%Y às %H:%M:%S %z}</time> · {escape(status)}</p>
  </div>
  <div class="gate-badge gate-badge--{'good' if gate_ok else 'low'}">
    QUALITY GATE: {'APROVADO' if gate_ok else 'ATENÇÃO'}
  </div>
</div></header>
<main>
  <nav aria-label="Seções do relatório">
    <a href="#resumo">Resumo</a>
    <a href="#camadas">Cobertura por serviço</a>
    <a href="#backend">Cobertura por arquivo (%)</a>
    <a href="#sonar">Análise estática e SonarQube</a>
    <a href="#unitarios-backend">Backend unitário</a>
    <a href="#unitarios-frontend">Frontend unitário</a>
    <a href="#ferramentas">Ferramentas NLP</a>
    <a href="#metodo">Metodologia</a>
  </nav>
  {"".join(sections)}
  <section id="metodo" aria-labelledby="metodo-title">
    <h2 id="metodo-title">Metodologia de medição</h2>
    <p>O backend foi medido com <code>pytest</code> + <code>Coverage.py --branch</code> em SQLite em memória (sem depender de rede externa nem credenciais de produção). O frontend foi medido com <code>node:test</code> e cobertura nativa V8/LCOV. As ferramentas de validação NLP e coletores foram medidas com <code>pytest tools/</code>.</p>
    <p>Os testes do recorte unitário rápido do backend também compõem a suíte completa (os totais consolidados no resumo executivo não contam duplicidade: somam Backend Completo + Frontend Unitário + Ferramentas).</p>
    <p>A cada execução de <code>python scripts/test-report.py</code>, o relatório HTML é salvo em <code>output/coverage/index.html</code> e espelhado em <code>backend/tests/relatorio-cobertura.html</code>, junto aos artefatos <code>backend-coverage.xml</code>, <code>backend-junit.xml</code> e <code>frontend-lcov.info</code> consumidos pelo SonarQube.</p>
  </section>
</main>
<script>{script}</script>
</body>
</html>
"""
    return html


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".test-report-", dir=OUTPUT.parent) as temporary:
        directory = Path(temporary)
        unit_dir, full_dir, tools_dir = (
            directory / "python-unit",
            directory / "python-full",
            directory / "python-tools",
        )
        unit_dir.mkdir()
        full_dir.mkdir()
        tools_dir.mkdir()
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
            export_sonar=True,
        )
        web = frontend_run(directory)
        tools = tools_run(tools_dir)
        static = run_static_analysis()
        unsuccessful = any(
            suite.errors or (suite.cases and suite.cases["failed"]) for suite in (unit, full, web, tools)
        )
        status = "Execução com falhas ou resultados incompletos" if unsuccessful else "Execução concluída com 100% de aprovação"
        html = render(full, unit, web, tools, static, status, datetime.now().astimezone(), unsuccessful)
        fresh_report = directory / OUTPUT.name
        fresh_report.write_text(html, encoding="utf-8")
        fresh_report.replace(OUTPUT)
        TESTS_HTML_OUTPUT.write_text(html, encoding="utf-8")
    print(f"\nRelatório HTML (CI): {OUTPUT}")
    print(f"Relatório HTML (pasta de testes): {TESTS_HTML_OUTPUT}")
    print(f"Artefatos Sonar: {SONAR_COVERAGE_XML.name}, {SONAR_JUNIT_XML.name}, {SONAR_FRONTEND_LCOV.name}")
    return int(unsuccessful)


if __name__ == "__main__":
    sys.exit(main())
