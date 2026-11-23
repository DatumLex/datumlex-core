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
            row["covered_lines"] - row["num_statements"],
            row["covered_branches"] - row["num_branches"],
            row["name"],
        ),
    )
    rendered = []
    for row in rows:
        lines, branches = row["num_statements"], row["num_branches"]
        missed = lines - row["covered_lines"]
        pct = (100 * row["covered_lines"] / lines) if lines else 100.0
        cls = tone(pct)
        name = escape(row["name"])
        missing = escape(row["missing"])
        missing_content = (
            f'<details class="lines"><summary>{number(missed)} linhas</summary><p>{missing}</p></details>'
            if missed
            else "—"
        )
        rendered.append(f"""<tr data-file="{name.lower()}">
          <th scope="row"><code>{name}</code></th>
          <td>
            <div class="bar-cell">
              <span class="pill pill--{cls}">{rate(row["covered_lines"], lines)}</span>
              <small>{counts(row["covered_lines"], lines) if lines else ""}</small>
            </div>
          </td>
          <td>{rate(row["covered_branches"], branches)}<small>{counts(row["covered_branches"], branches) if branches else ""}</small></td>
          <td>{missing_content}</td>
        </tr>""")
    is_full = section_id == "backend"
    search_box = (
        f'<label class="filter-box">Filtrar arquivo: '
        f'<input type="search" placeholder="Ex.: research, nlp, legal_chat..." '
        f'oninput="filterTable(this, \'{section_id}-tbody\')"></label>'
        if len(rows) > 8
        else ""
    )
    return f'''<details class="files"{" open" if not is_full else ""}>
      <summary>Cobertura por arquivo <span>({number(len(rows))})</span></summary>
      {search_box}
      <div class="table-scroll">
        <table aria-label="Cobertura por arquivo — {escape(scope)}">
          <thead><tr><th scope="col">Arquivo</th><th scope="col">Linhas</th><th scope="col">Ramificações</th><th scope="col">Linhas a cobrir</th></tr></thead>
          <tbody id="{section_id}-tbody">{"".join(rendered)}</tbody>
        </table>
      </div>
    </details>'''


def render_layers_section(layers):
    cards = []
    for layer in layers:
        pct_str = rate(layer["covered_lines"], layer["num_statements"])
        cls = tone(layer["pct"])
        cards.append(f"""<article class="layer-card">
          <div class="layer-head">
            <div>
              <h3>{escape(layer["title"])}</h3>
              <p class="layer-sub">{escape(layer["subtitle"])}</p>
            </div>
            <span class="pill pill--{cls}">{pct_str}</span>
          </div>
          <div class="progress" role="progressbar" aria-valuenow="{layer['pct']:.1f}" aria-valuemin="0" aria-valuemax="100">
            <span class="progress-fill progress-fill--{cls}" style="width:{min(100.0, layer['pct']):.1f}%"></span>
          </div>
          <div class="layer-meta">
            <span><code>{escape(layer["prefix"])}</code></span>
            <span>{number(layer["files"])} arquivo(s)</span>
            <span>Linhas: {counts(layer["covered_lines"], layer["num_statements"])}</span>
            <span>Ramificações: {rate(layer["covered_branches"], layer["num_branches"])}</span>
          </div>
        </article>""")
    return f'''<section id="camadas" aria-labelledby="camadas-title">
      <h2 id="camadas-title">Cobertura por camada e serviço</h2>
      <p class="muted">Agrupamento direto da execução medida sobre os serviços de domínio, APIs, motor NLP v2, ETL, segurança e frontend.</p>
      <div class="layer-grid">{"".join(cards)}</div>
    </section>'''


def render_sonar_section(static, sonar_files_status):
    ruff_crit = "—" if static.ruff_critical is None else number(static.ruff_critical)
    ruff_style = "—" if static.ruff_style is None else number(static.ruff_style)
    es_err = "—" if static.eslint_errors is None else number(static.eslint_errors)
    es_warn = "—" if static.eslint_warnings is None else number(static.eslint_warnings)

    kpis = [
        metric(
            "Ruff · Erros críticos (F/E9)",
            ruff_crit,
            static.ruff_note or "Bugs, nomes indefinidos e imports mortos",
            badge_tone="good" if static.ruff_critical == 0 else "low",
        ),
        metric(
            "Ruff · Avisos de estilo",
            ruff_style,
            "Code smells de formatação em backend/src",
            badge_tone="good" if static.ruff_style == 0 else "warn",
        ),
        metric(
            "ESLint · Erros Frontend",
            es_err,
            static.eslint_note or f"{number(static.eslint_files)} arquivos JS/JSX verificados",
            badge_tone="good" if static.eslint_errors == 0 else ("low" if static.eslint_errors else ""),
        ),
        metric(
            "ESLint · Avisos Frontend",
            es_warn,
            "Regras React Hooks e qualidade JS",
            badge_tone="good" if static.eslint_warnings == 0 else "",
        ),
    ]
    artifact_rows = "".join(
        f"<tr><td><code>{escape(name)}</code></td><td>{escape(desc)}</td>"
        f"<td><span class='pill pill--{'good' if exists else 'warn'}'>{'Gerado / Pronto' if exists else 'Pendente'}</span></td></tr>"
        for name, desc, exists in sonar_files_status
    )
    rules_note = ""
    if static.ruff_top_rules:
        chips = " · ".join(f"<code>{escape(code)}</code> ({n})" for code, n in static.ruff_top_rules)
        rules_note = f"<p class='muted' style='margin-top:10px'>Regras Ruff mais frequentes (estilo): {chips}</p>"

    return f'''<section id="sonar" aria-labelledby="sonar-title">
      <h2 id="sonar-title">Qualidade estática e integração SonarQube</h2>
      <p class="muted">Análise estática executada nesta rodada (Ruff + ESLint) combinada com a configuração oficial do projeto SonarQube (<code>br.edu.fatec:datumlex</code>) para Python e JavaScript.</p>
      <dl class="metrics">{"".join(kpis)}</dl>
      {rules_note}
      <div class="table-scroll">
        <table aria-label="Artefatos de integração SonarQube">
          <thead><tr><th scope="col">Artefato / Configuração</th><th scope="col">Finalidade no SonarQube</th><th scope="col">Status</th></tr></thead>
          <tbody>{artifact_rows}</tbody>
        </table>
      </div>
      <p class="muted" style="margin-top:12px">
        Execução local com Docker: <code>docker compose -f docker-compose.sonar.yml up -d sonarqube</code> e
        <code>SONAR_TOKEN=&lt;token&gt; docker compose -f docker-compose.sonar.yml run --rm sonar-scanner</code>.
        No GitHub Actions, o workflow <code>.github/workflows/sonar.yml</code> consome automaticamente os segredos <code>SONAR_TOKEN</code> e <code>SONAR_HOST_URL</code>.
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
        render_sonar_section(static, sonar_files_status),
        summarize(
            "unitarios-backend",
            "Backend · testes unitários (recorte rápido)",
            "Contexto analítico, data local e contrato de anotações, com casos em "
            "<code>backend/tests/test_analytical_context.py</code>, <code>backend/tests/test_period.py</code> e <code>backend/tests/test_annotation_contract.py</code>.",
            unit,
        ),
        summarize(
            "unitarios-frontend",
            "Frontend · testes unitários (Node.js)",
            f"{len(web.files)} de {frontend_count} arquivos JavaScript/JSX em <code>frontend/src</code> foram medidos. "
            "O Node.js mede os módulos carregados pelos testes em <code>frontend/tests/unit/</code>.",
            web,
        ),
        summarize(
            "ferramentas",
            "Ferramentas · validação NLP e coletores",
            "Testes automatizados em <code>tools/doctrine/</code> e <code>tools/nlp_validation/</code> garantindo contratos de coleta e cobertura.",
            tools,
        ),
        summarize(
            "backend",
            "Backend · suíte completa (unitários + integração)",
            "47 arquivos de teste exercitando APIs REST, serviços de domínio, Chat Gemini, NLP v2, ETL DataJud/Pangea, segurança e settings de produção. Cobertura de <code>backend/src</code> sem migrações.",
            full,
        ),
    ]
    styles = """
      :root { color-scheme: light; font-family: system-ui, -apple-system, sans-serif; color: #14293c; background: #f3f6f8; line-height: 1.55; }
      * { box-sizing: border-box; }
      body { margin: 0; }
      header { background: linear-gradient(135deg, #102a3f 0%, #14334a 55%, #0c4d45 100%); color: #fff; }
      .wrap, main { max-width: 1180px; margin: auto; padding-inline: clamp(16px,4vw,52px); }
      header .wrap { padding-block: 40px 32px; display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end; gap: 16px; }
      h1 { margin: 4px 0 8px; font-size: clamp(1.9rem,4.5vw,3rem); line-height: 1.1; letter-spacing: -.03em; }
      .brand { margin: 0; color: #b7ebd9; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; font-size: .85rem; }
      header p:last-child { margin: 0; color: #dce9f1; }
      .gate-badge { padding: 10px 18px; border-radius: 999px; font-weight: 700; font-size: .92rem; letter-spacing: .03em; border: 1px solid rgba(255,255,255,.28); }
      .gate-badge--good { background: rgba(16,185,129,.22); color: #d1fae5; }
      .gate-badge--low { background: rgba(239,68,68,.26); color: #fee2e2; }
      nav { padding-block: 18px 8px; display: flex; flex-wrap: wrap; gap: 8px 16px; }
      nav a { color: #07594e; font-weight: 650; text-underline-offset: 3px; font-size: .94rem; }
      section { margin: 18px 0; padding: clamp(16px,3vw,28px); background: #fff; border: 1px solid #d9e3e9; border-radius: 12px; scroll-margin-top: 12px; box-shadow: 0 1px 2px rgba(16,42,63,.04); }
      h2 { font-size: clamp(1.2rem,2.6vw,1.55rem); margin: 0 0 4px; line-height: 1.3; }
      h3 { margin: 0; font-size: 1rem; color: #14293c; }
      .muted { overflow-wrap: anywhere; color: #405a6d; margin: 0; font-size: .94rem; }
      .alert { color: #991b1b; background: #fef2f2; border: 1px solid #fecaca; padding: 10px 12px; border-radius: 8px; }
      .metrics { display: grid; grid-template-columns: repeat(auto-fit,minmax(160px,1fr)); gap: 10px; margin: 18px 0 8px; }
      .metric { padding: 12px 13px; border: 1px solid #d9e8e5; background: #f4faf8; border-radius: 10px; }
      .metric--good { border-color: #bbf7d0; background: #f0fdf4; }
      .metric--warn { border-color: #fde68a; background: #fffbeb; }
      .metric--low { border-color: #fecaca; background: #fef2f2; }
      dt { font-size: .82rem; color: #304d56; font-weight: 600; }
      dd { margin: 2px 0 0; color: #07594e; font-weight: 750; font-size: 1.35rem; }
      .metric--warn dd { color: #92400e; }
      .metric--low dd { color: #991b1b; }
      small { display: block; font-size: .78rem; font-weight: 500; color: #405a6d; }
      dd, td { font-variant-numeric: tabular-nums; }
      .layer-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(270px,1fr)); gap: 12px; margin-top: 16px; }
      .layer-card { border: 1px solid #dce6ec; border-radius: 10px; padding: 14px; background: #fbfdfe; }
      .layer-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; margin-bottom: 10px; }
      .layer-sub { margin: 2px 0 0; font-size: .82rem; color: #4b6476; }
      .progress { height: 9px; background: #e2ecf1; border-radius: 999px; overflow: hidden; margin-bottom: 10px; }
      .progress-fill { display: block; height: 100%; border-radius: 999px; }
      .progress-fill--good { background: #0f766e; }
      .progress-fill--warn { background: #d97706; }
      .progress-fill--low { background: #dc2626; }
      .layer-meta { display: flex; flex-wrap: wrap; gap: 6px 12px; font-size: .8rem; color: #405a6d; }
      .pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: .8rem; font-weight: 700; white-space: nowrap; }
      .pill--good { background: #dcfce7; color: #166534; }
      .pill--warn { background: #fef3c7; color: #92400e; }
      .pill--low { background: #fee2e2; color: #991b1b; }
      .bar-cell { display: flex; flex-direction: column; gap: 2px; align-items: flex-start; }
      summary { cursor: pointer; color: #07594e; font-weight: 650; }
      summary span { color: #405a6d; }
      .filter-box { display: flex; align-items: center; gap: 8px; margin-top: 12px; font-size: .88rem; color: #304d56; }
      .filter-box input { padding: 6px 10px; border: 1px solid #cbd8e0; border-radius: 6px; min-width: 240px; font: inherit; }
      .table-scroll { margin-top: 10px; overflow-x: auto; }
      table { border-collapse: collapse; width: 100%; text-align: left; font-size: .88rem; }
      th, td { padding: 9px 10px; border-bottom: 1px solid #e1e9ee; vertical-align: top; }
      thead { background: #e9f1f5; }
      tbody th { font-weight: 500; overflow-wrap: anywhere; width: 52%; }
      tbody tr:nth-child(even) { background: #f8fbfc; }
      .lines p { margin: 4px 0; overflow-wrap: anywhere; }
      code { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .88em; background: #eef4f7; padding: 1px 4px; border-radius: 4px; }
      #metodo { margin-bottom: 36px; }
      #metodo p { margin: 8px 0; }
      @media (max-width: 560px) {
        table { min-width: 510px; }
        header .wrap { padding-block: 28px 24px; }
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
    """
    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DatumLex · Painel de Testes Automatizados, Cobertura e SonarQube</title>
<style>{styles}</style>
</head>
<body>
<header><div class="wrap">
  <div>
    <p class="brand">DatumLex · Engenharia de Qualidade</p>
    <h1>Testes Automatizados e Cobertura</h1>
    <p>Gerado em <time datetime="{generated.isoformat()}">{generated:%d/%m/%Y às %H:%M:%S %z}</time> · {escape(status)}</p>
  </div>
  <div class="gate-badge gate-badge--{'good' if gate_ok else 'low'}">
    Quality Gate · {'APROVADO' if gate_ok else 'ATENÇÃO'}
  </div>
</div></header>
<main>
  <nav aria-label="Seções do relatório">
    <a href="#resumo">Resumo / Quality Gate</a>
    <a href="#camadas">Cobertura por serviço</a>
    <a href="#sonar">Análise estática & SonarQube</a>
    <a href="#unitarios-backend">Backend unitário</a>
    <a href="#unitarios-frontend">Frontend unitário</a>
    <a href="#ferramentas">Ferramentas NLP</a>
    <a href="#backend">Backend completo</a>
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
