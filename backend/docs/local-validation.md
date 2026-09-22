# Local validation - 2026-09-17

Working-tree implementation based on `datumlex-core` commit `9dee323`. No commit or push was created.

## Executed checks

- Django system check: passed.
- Initial migration on local SQLite: passed.
- Migration drift check (`makemigrations --check --dry-run`): no changes detected.
- `manage.py test tests`: 20 tests passed in an isolated test database.
- Ruff lint and format checks: passed.
- Read-only HTTP smoke against `127.0.0.1:8000`: passed; statistics, instance totals and
  paginated record count reconciled to 200, invalid court returned 400, merit fields remained unavailable.

## Real source run

Official DataJud TJDFT endpoint, public records, explicit subjects `10431,10433,10439`,
filing dates `2023-01-01` through `2026-09-17`, page size 100, two pages.
The public access key was retrieved from the official CNJ page at execution time and used only
in the process environment. It was not stored in tracked files or this report.

| Run | Fetched | Created | Updated/replayed | Rejected | Local total after run |
|---|---:|---:|---:|---:|---:|
| 1 | 200 | 200 | 0 | 0 | 200 |
| 2 (same query) | 200 | 0 | 200 | 0 | 200 |

Both runs intentionally paused at the two-page boundary. Source-reported matching total was
22,757 at observation time; **only 200 documents are loaded**, not the full population.
Observed degrees: G1 47, G2 36, JE 117. These are document counts, not appeal outcomes.
The rerun verifies no duplicate fact/bridge growth for the same live sample.

SQLite data and exact run timestamps/cursors are in the ignored local `data/datumlex.sqlite3`.
The metadata sample contains additional co-occurring subjects, preserved through the subject bridge.
Those subjects do not establish independently collected coverage for their practice areas.

## Limits

Docker Desktop's database engine was not running. PostgreSQL configuration and migrations are
provided but PostgreSQL integration was not executed. No deployment, frontend connection, full
taxonomy expansion, full extraction, independent modeling approval or merit classification is claimed.
The backend server was started locally for HTTP validation; use the README command to restart it.
