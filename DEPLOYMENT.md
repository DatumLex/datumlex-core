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

The backend start command applies migrations, provisions the support account, and runs an
idempotent bootstrap before starting Gunicorn. The bootstrap loads the complete TJDFT scope
used by the dashboard (subjects `10431`, `10433`, and `10439`, from 2023-01-01 through
2026-09-27) only when no
completed deployment extraction exists; an interrupted run is resumed from its saved cursor.
This keeps the free service self-contained without reloading the dataset after each sleep or
redeploy. The local development database is intentionally ignored by Git and is never included
in a deploy.

The migrations run in the start command because Render pre-deploy commands are unavailable
to free web services.

## Limitations of the free configuration

The Blueprint uses free plans for an initial academic demonstration. Render's free PostgreSQL
database expires after 30 days, has no backups, and must not be treated as durable production
storage. Upgrade the database before relying on it for a long-lived public deployment.

## Custom domains

For a custom domain, use sibling hosts such as `app.example.com` and `api.example.com`, then
update `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, and the frontend's
`VITE_API_BASE_URL`. Rebuild the frontend after changing its API URL.
