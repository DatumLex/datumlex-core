# DatumLex backend

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
The local database is `data/datumlex.sqlite3`; `.env`, raw data, database files and `.venv` are ignored by Git.
The development server is local only, not a production deployment.

## Extract real DataJud data

Put the current **public** CNJ key in `.env` as `DATAJUD_API_KEY=...` without quotes or the
`Authorization:` prefix. Obtain it from the [official access page](https://datajud-wiki.cnj.jus.br/api-publica/acesso/).
The key is never included in extraction metadata or API responses.

```powershell
.venv/Scripts/python.exe manage.py extract_datajud --subjects 10431,10433,10439 --start 2023-01-01 --end 2026-09-17 --page-size 100 --max-pages 2
```

This command intentionally loads a **bounded sample** (up to 200 returned documents).
Use the run ID printed by the command to continue:

```powershell
.venv/Scripts/python.exe manage.py extract_datajud --resume 1 --max-pages 5
```

`--max-pages 0` traverses until the source returns an empty page. The default is five pages
of 100 records, to avoid accidentally downloading a whole court. `--end` defaults to today.
The saved scope and page size take precedence when resuming. Run only one extractor against
this local database at a time. A still-running/completed run cannot be resumed. If a process
was force-killed, first verify it has stopped before changing that run from `running` to `failed`
in a Django shell; the last committed page/cursor is the recovery boundary.

Only public TJDFT records (`nivelSigilo=0`) are loaded. Other courts, malformed process
identifiers, out-of-range dates and absent required dimensions are rejected and counted.
Rejection reasons/source IDs are stored separately without retaining the rejected payload.

### Scope and dates

- `10431`: Responsabilidade Civil; `10433`: Indenização por Dano Moral; `10439`: Indenização por Dano Material.
- These are **explicit codes**, not a complete or automatically expanded descendant taxonomy.
  The default without `--subjects` is only `10431`. Approve the full taxonomy before claiming
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
| `/api/statistics/` | Document count, distinct CNJ process numbers, unavailable merit fields |
| `/api/distribution/` | Explicit unavailable state until merit classification is validated |
| `/api/instances/` | Records by filing year/quarter and degree; no appeal/reversal inference |
| `/api/processes/` | Paginated normalized metadata; raw payload/movements are not returned |

Filters: `court=TJDFT`, `subject=<exact code>`, `start=YYYY-MM-DD`, `end=YYYY-MM-DD`,
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
Instance/process endpoints disclose `outcome_filter_applied=false`. Distribution remains unavailable.
Statistics retain the same population for all outcome selections.

Counts are real loaded **DataJud documents**, not analyzed appeals. The same CNJ process may have
G1/G2 documents; multiple subjects never multiply counts. `analyzed_appeals`, `grant_rate`,
`denial_rate`, granted/denied counts and the binary denominator deliberately remain `null`.
There is no validated movement-to-outcome mapping in the supplied model. In particular, `G2`,
"procedência" and a procedural event must not be equated with a granted appeal.
This backend implements extraction and the documented process model, not a completed merit release.

`status=partial` describes loaded volume, `empty` describes no local matches, and `unavailable`
describes unsupported merit data. Latest-run metadata is global; its scope is returned explicitly
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
# postgresql://datumlex:<password>@127.0.0.1:5433/datumlex
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py test tests
```

This uses port 5433 and a named local volume. Changing DATABASE_URL does not copy SQLite data;
rerun extraction/import against the selected database. Credentials and data remain local.
Production deployment, authentication/rate limiting for public exposure, scheduled extraction,
full taxonomy, outcome methodology, and frontend integration are separate work.

## Validation

```powershell
.venv/Scripts/python.exe manage.py check
.venv/Scripts/python.exe manage.py makemigrations --check --dry-run
.venv/Scripts/python.exe manage.py test tests -v 2
.venv/Scripts/ruff.exe check .
.venv/Scripts/ruff.exe format --check .
```

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
