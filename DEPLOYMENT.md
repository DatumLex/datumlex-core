# Render deployment

`render.yaml` provisions three resources for the college-project deployment:

- `datumlex-web-pedromattos`: Vite static frontend;
- `datumlex-api-pedromattos`: Django web service;
- `datumlex-db-pedromattos`: PostgreSQL 17 database.

## Required secrets

The Render Blueprint prompts for two values. Do not commit either value:

- `DATUMLEX_SUPPORT_PASSWORD`: the initial immutable `suport` account password;
- `DATAJUD_API_KEY`: the current public key published by CNJ, without the `APIKey ` prefix.

The Blueprint generates `DJANGO_SECRET_KEY` and injects the database connection automatically.

## Initial data

Free web services apply migrations and provision support in the build command.
Provisioning does not reset an existing support password. Migrations may change the
database even if a later deployment step fails; use compatible migrations and backups.
Data extraction is deliberately separate from application startup: restarting or
deploying the API must not start an unlimited collection or reclaim a running extractor.

Migrations create an empty database. After the first deploy, either restore a compatible
PostgreSQL dump or run the bounded DataJud extractor from the backend service. The local
development database is intentionally ignored by Git and is never included in a deploy.

## Historical data and PDF summaries

DataJud extraction and dashboard filters accept filing dates from **2016-01-01** through
today. The current year is incomplete. A date range does not establish complete court
coverage. Existing saved runs keep their original scopes and cursors.

For a bounded collection, run from `backend/` with the intended database configured:

```powershell
.venv/Scripts/python.exe manage.py extract_datajud --court TJDFT --start 2016-01-01 --subjects 10431,10433,10439 --page-size 100 --max-pages 1
# Repeat for --court STJ. Continue using the printed --resume ID.
```

The dashboard's **Exportar resumo em PDF** button downloads an authenticated report of
the applied court, subject and period selection. The PDF includes DataJud document counts,
distinct CNJ numbers, binary rates and denominator, exclusions, annual volume, collection
time and limitations. It queries a consistent database snapshot at export time; later
collection can make it differ from a dashboard loaded earlier. It does not merge Pangea
references or unreviewed NLP evidence into the DataJud metrics. The existing NLP snapshot
report remains available separately for reviewed textual evidence.

`GET /api/report.pdf/` uses the same query validation and court permissions as statistics.
Reports are marked `no-store`; no judicial record, user account or password is modified.

## Limitations of the free configuration

The Blueprint uses free plans for an initial academic demonstration. Render's free PostgreSQL
database expires after 30 days, has no backups, and must not be treated as durable production
storage. Upgrade the database before relying on it for a long-lived public deployment.

## Custom domains

For a custom domain, use sibling hosts such as `app.example.com` and `api.example.com`, then
update `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, and the frontend's
`VITE_API_BASE_URL`. Rebuild the frontend after changing its API URL.
