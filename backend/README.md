# DatumLex backend

BDJur integration: see the [bounded source-feasibility report](docs/bdjur-feasibility.md)
(#101). Tested direct routes returned 403; no approved doctrine corpus is claimed.

Sprint 2 baseline: see the [2026-10-21 audit and 45-issue traceability matrix](docs/sprint-2-baseline-audit.md)
for reproduced validation gaps, delivery dependencies and review boundaries.

Sprint 2 filter design: [proposed canonical analytical-context contract](docs/analytical-context.md)
and its independently calculated examples (#165). Existing API behavior remains
unchanged until independent contract/model review and #166 implementation.

Update 2026-09-27: analytics now require an approved session and authorized court. Login, registration, user management, immutable support provisioning, and audit are implemented. See [access control and deployment](docs/access-control.md), which supersedes earlier unauthenticated API/startup examples below.

Update 2026-09-22: the backend now uses the resource dimensional schema based on
`datumlex.session.sql`, with new process, degree and result dimensions. See
[schema mapping and fresh database setup](docs/resource-schema.md). Migration
`0002_resource_schema` rebuilds the warehouse and discards v1 rows: use the new
`datumlex_v2` database/volume. Do not execute the reference SQL manually.

Update 2026-10-18: the API calculates exploratory per-document rates for TJDFT (G2/TR) and STJ (SUP), using explicit CNJ TPU result movements. Migration `0004_stj_merit_outcomes` reclassifies the already-loaded STJ snapshot. See the [methodology, exclusions, and limitations](docs/merit-methodology.md). Individual appeals are not counted.

Local Django backend for **DataJud -> normalization -> dimensional warehouse -> JSON API**.
Python 3.12+, Django 5.2 LTS. SQLite works without a database server; PostgreSQL is configured
through `DATABASE_URL`. No frontend changes are required to run this backend independently.

## Start locally (PowerShell)

```powershell
cd datumlex-core/backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py runserver 127.0.0.1:8000
```

If the virtual environment already exists, start with `migrate` and `runserver`.
Open <http://127.0.0.1:8000/api/health/> or <http://127.0.0.1:8000/api/statistics/>.
The fallback local database is `data/datumlex_v2.sqlite3`; `.env`, raw data, database files and `.venv` are ignored by Git.
The development server is local only, not a production deployment.

## Extract real DataJud data

Put the current **public** CNJ key in `.env` as `DATAJUD_API_KEY=...` without quotes or the
`Authorization:` prefix. Obtain it from the [official access page](https://datajud-wiki.cnj.jus.br/api-publica/acesso/).
The key is never included in extraction metadata or API responses.

```powershell
.venv/Scripts/python.exe manage.py extract_datajud --subjects 10431,10433,10439 --start 2023-01-01 --end 2026-09-17 --page-size 100 --max-pages 2
```

This command intentionally loads a **bounded sample** (up to 200 returned documents).
Repeating an extraction with the exact same court, subjects, dates and page size now resumes
the latest matching paused/failed run from its saved cursor. The run ID is still printed, and
you can explicitly continue it with:

```powershell
.venv/Scripts/python.exe manage.py extract_datajud --resume 1 --max-pages 5
```

### Sincronização automática TJDFT + STJ

No Windows, instale a tarefa automática uma única vez executando
`backend/scripts/install_datajud_schedule.ps1` com PowerShell. A tarefa inicia uma carga histórica
desde 2023 para TJDFT e STJ, dois lotes de 100 registros por tribunal por execução. Se houver mais
páginas, ela retoma o cursor salvo nas execuções diárias seguintes; depois de concluir o histórico,
passa a buscar atualizações pela data de indexação (`dataHoraUltimaAtualizacao`) nos dois tribunais,
com sobreposição de três dias. A seleção ampliada inclui os ramos TPU de Direito Civil, Consumidor,
Saúde, Previdenciário, Administrativo, Tributário, Processual Civil, Penal, Trabalho, Infância e
Meio Ambiente, com códigos de subassuntos conhecidos para consumidor, saúde, previdenciário e
processo civil. A lista inclui 10431, 10433 e 10439. A consulta usa códigos explícitos e não declara
cobertura de todos os descendentes da TPU; a origem taxonômica é a [consulta pública do SGT/CNJ](https://www.cnj.jus.br/sgt/consulta_publica_assuntos.php).

A tarefa é executada diariamente às 2h enquanto sua sessão do Windows estiver conectada, mesmo
sem uma janela de terminal aberta, e tenta iniciar na instalação. Usa o `.env` e o banco já configurados para o backend. A saída fica em
`backend/data/datajud-scheduler.log` (com rotação automática), e cada execução também registra
tribunal, escopo, cursor e contagens em `extraction_run`. O painel continua consultando a API
periodicamente. A sincronização não representa cobertura completa e não substitui a revisão
jurídica das avaliações de precedentes.

### Integração Pangea/BNP

A tarefa consulta a busca pública do Pangea/BNP, filtrando o órgão STJ e usando o catálogo público
de espécies. Essa rota de pesquisa não exige credenciais OAuth; configure
`PANGEA_SEARCH_BASE_URL` somente se precisar apontar para outro ambiente. A integração importa
tese, questão, situação, metadados e processos paradigma explicitamente listados. Registra também
execução, cobertura, paginação e hash do payload. `ultimaAtualizacao` é guardada como atualização
da fonte, nunca como data de julgamento/publicação. As referências entram como pendentes de
aprovação e não contam nos indicadores até revisão jurídica. A busca automática cobre
responsabilidade civil, consumidor, saúde, previdenciário, administrativo, tributário e processo
civil, até cinco páginas de 100 por tema a cada execução. Em uma coleta ao vivo, as sete buscas
retornaram 2.414 resultados, consolidados em 815 referências STJ únicas. Resultados repetidos em temas diferentes
atualizam a proveniência da mesma referência em vez de criar duplicatas.

Para validar/conectar imediatamente pela aplicação, o comando é
`manage.py sync_pangea --query "direito do consumidor" --page-size 100 --max-pages 5`. Para reconciliar citações explícitas
com os registros TJDFT carregados, use `manage.py match_stj_citations`; a tarefa diária executa
essa reconciliação após sincronizar as fontes. Apenas números CNJ completos são comparados.
Correspondências de identificador não são avaliações de aderência e ficam fora das taxas.
O cliente OAuth legado (`BNP_API_*`) permanece disponível para outros recursos autenticados,
mas não é usado por essa pesquisa pública. Consulte o [guia Pangea da PDPJ-Br](https://docs.pdpj.jus.br/servicos-negociais/pangeabnp/)
para distinguir os recursos públicos do portal dos recursos negociais autenticados.

Para administrar a tarefa depois da instalação, use o aplicativo **Agendador de Tarefas** do
Windows e procure `DatumLex DataJud TJDFT-STJ`. Se a chave DataJud não estiver configurada no
`.env` ou o banco/backend não estiver disponível, o erro é registrado no log e a tarefa tenta
novamente no próximo horário.

`--max-pages 0` traverses until the source returns an empty page. The default is five pages
of 100 records, to avoid accidentally downloading a whole court. `--end` defaults to today.
The saved scope and page size take precedence when resuming. Run only one extractor against
this local database at a time. A still-running/completed run cannot be resumed. If a process
was force-killed, first verify it has stopped before changing that run from `running` to `failed`
in a Django shell; the last committed page/cursor is the recovery boundary.

Only public records (`nivelSigilo=0`) from the selected supported court are loaded. Other courts, malformed process
identifiers, out-of-range dates and absent required dimensions are rejected and counted.
Rejection reasons/source IDs are stored separately without retaining the rejected payload.

### Scope and dates

- `10431`: Civil Liability; `10433`: Compensation for Non-Pecuniary Damage; `10439`: Compensation for Pecuniary Damage.
- These are **explicit codes**, not a complete or automatically expanded descendant taxonomy.
  The default uses a curated list of explicit TPU roots and subtopics; it does not infer every
  descendant. The complete scope is in `src/db/subject_catalog.py`. Approve the full taxonomy before claiming
  complete Civil Liability coverage. References: [CNJ hierarchy](https://www.cnj.jus.br/sgt/visualizar_sugestoes.php?codigo=366)
  and [TPU subject table](https://www.tjsp.jus.br/Download/GeraisIntranet/SPI/AreaConciliacao.pdf).
- The period is the **filing date** (`dataAjuizamento`), not judgment date. Therefore this
  extraction does not claim to include every appeal judged since 2023 in older cases.
- Real TJDFT observations on 2026-09-17 included `20240627103004`. Its index aggregation treated
  that numeric value as epoch milliseconds. The query matches both ISO dates and compact numeric
  dates, then parses the original source value and checks the actual date before loading.
- Timezone-less source timestamps use UTC as an explicit technical convention. Legal/local
  date semantics require reconciliation before a merit release.
- Sorting uses `@timestamp` plus `id.keyword` as a tie-breaker. The client refuses missing,
  null or stalled cursors and incomplete/shard-failed responses. Retries are bounded for
  network errors, HTTP 429 and temporary server errors.
- DataJud is a changing index, not a transactionally frozen snapshot. A completed traversal
  does not establish national coverage, source correctness, or a full judicial census.

### Offline source response

```powershell
.venv/Scripts/python.exe manage.py extract_datajud --input data/sample.json --subjects 10433 --end 2026-09-17
```

Input must be a DataJud JSON response with `hits.hits` entries containing `_id` and `_source`.
File imports are always marked `sample`, require no key and cannot resume a remote run.

## API

All routes are read-only `GET`, return JSON and use a trailing slash.

| Route | Result |
|---|---|
| `/api/health/` | Database connectivity and migration/table availability |
| `/api/scope/` | Loaded subject codes, period, source and latest-run context |
| `/api/statistics/` | Document count, distinct CNJ process numbers, document-level grant/denial proxy and exclusions |
| `/api/distribution/` | Grant/denial proportions over the eligible binary document denominator |
| `/api/instances/` | Records by filing year/quarter and degree; no appeal/reversal inference |
| `/api/processes/` | Paginated normalized metadata; raw payload/movements are not returned |
| `/api/alignment/` | Validated TJDFT-to-STJ/BDJur links, adherence/divergence rates, quarterly trends and citations |

Filters: `court=TJDFT|STJ`, `subject=<exact code>`, `start=YYYY-MM-DD`, `end=YYYY-MM-DD`,
`outcome=all|granted|denied`. With no subject, results cover all locally loaded subjects.
`page` (default 1) and `page_size` (default 25, max 100) apply to `/api/processes/`.
Dates are inclusive and limited to 2023 through today. Unknown parameters, repeated parameters,
invalid dates/codes/outcomes return HTTP 400. Database failures return HTTP 503 without internal details;
unsupported methods return HTTP 405. JSON `null` is unavailable, not a numeric zero.

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/statistics/?subject=10433&start=2023-01-01&end=2026-09-17'
Invoke-RestMethod 'http://127.0.0.1:8000/api/instances/'
Invoke-RestMethod 'http://127.0.0.1:8000/api/processes/?page=1&page_size=10'
```

The outcome parameter is accepted for contract continuity but **does not filter process volume**.
Instance/process endpoints disclose `outcome_filter_applied=false`.
Statistics retain the same population for all outcome selections.

Counts are real loaded **DataJud documents**, not analyzed appeals. The same CNJ process may have
G1/G2/SUP documents; multiple subjects never multiply counts. `analyzed_appeals` remains `null`.
Grant and denial rates are limited to mapped TPU movements and the binary denominator. They are
document-level proxies, not appeal-grain counts or tribunal-wide rates. See the methodology for
supported codes and exclusions.

`status=partial` describes loaded volume, `empty` describes no local matches, and `unavailable`
describes a zero binary denominator. Latest-run metadata is global; its scope is returned explicitly
and is not a claim of completeness for the user's filters. Records from different runs can coexist.

## Model and dictionary

See [the implementation dictionary](docs/data-dictionary.md), based on the
[reference diagrams](https://github.com/DatumLex/documentation/blob/main/architecture/Dimensional-Model.md).
The Django migration is the executable local schema. Changes to the reference are documented,
not presented as team approval or production modeling acceptance.

## PostgreSQL

With Docker Desktop running, choose a local password and start a separate local database:

```powershell
$env:POSTGRES_PASSWORD = '<choose-local-password>'
docker compose up -d db
# Set DATABASE_URL in .env; URL-encode special characters in the password.
# postgresql://datumlex:<password>@127.0.0.1:5433/datumlex_v2
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py test tests
```

This uses loopback port 5433 and the new `datumlex_pg_v2` named volume. Changing DATABASE_URL does not copy SQLite data;
rerun extraction/import against the selected database. Credentials and data remain local.
Production deployment, authentication/rate limiting for public exposure, scheduled extraction,
full taxonomy, outcome methodology, and frontend integration are separate work.

## Validation

```powershell
.venv/Scripts/python.exe manage.py check
.venv/Scripts/python.exe manage.py makemigrations --check --dry-run
.venv/Scripts/python.exe manage.py test tests -v 2
.venv/Scripts/python.exe -m pytest
.venv/Scripts/ruff.exe check .
.venv/Scripts/ruff.exe format --check .
```

Pytest discovers the backend suite in `tests/` and uses `config.test_settings` via pytest-django.
That configuration uses an in-memory SQLite database and removes support-account credentials, so
pytest does not connect to or modify the local development database. Install pytest and pytest-django
along with the other development tools using `pip install -r requirements-dev.txt`.

Tests use a separate temporary database and explicitly synthetic fixtures. They cover normalization,
privacy/scope rejection, leading zeroes, pagination/retries, interrupted-page rollback, resume,
idempotent loading, bridge uniqueness, stale-source protection, API filters, nulls, CORS and counts.
They never insert fixtures into `data/datumlex.sqlite3` or call live DataJud.

For the read-only HTTP smoke test after starting the server:

```powershell
.venv/Scripts/python.exe scripts/smoke_http.py
```

## Source references

- [DataJud endpoints](https://datajud-wiki.cnj.jus.br/api-publica/endpoints/)
- [Official pagination example](https://datajud-wiki.cnj.jus.br/api-publica/exemplos/exemplo3/)
- [Django database support](https://docs.djangoproject.com/en/5.2/ref/databases/)
# DataJud court ingestion

The `extract_datajud` management command supports `TJDFT` and `STJ`. Example:

```sh
python manage.py extract_datajud --court STJ --start 2023-01-01 --end 2026-10-18 --subjects 10431 --max-pages 5
```

Each extraction run retains its court, explicit subject codes, date window,
source totals, pagination status and rejected-record count. DataJud IDs are
namespaced by court. The dashboard reports loaded-record coverage as partial;
it does not assert complete jurisprudence coverage.

The STJ feed is process metadata, not a curated precedent corpus. Comparing
local TJDFT reasoning with binding or persuasive STJ precedents requires an
approved, sourced precedent collection and a reviewable mapping from decisions
to legal theses. BDJur doctrine likewise must be separately ingested with its
approval and citation metadata. The application does not label cases as aligned
or misaligned from process metadata alone. See [the approved-corpus import and
review workflow](docs/precedent-alignment.md) for cited, human-validated
TJDFT-to-STJ/BDJur assessments.
