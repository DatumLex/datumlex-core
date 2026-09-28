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

Migrations create an empty database. After the first deploy, either restore a compatible
PostgreSQL dump or run the bounded DataJud extractor from the backend service. The local
development database is intentionally ignored by Git and is never included in a deploy.

## Limitations of the free configuration

The Blueprint uses free plans for an initial academic demonstration. Render's free PostgreSQL
database expires after 30 days, has no backups, and must not be treated as durable production
storage. Upgrade the database before relying on it for a long-lived public deployment.

## Custom domains

For a custom domain, use sibling hosts such as `app.example.com` and `api.example.com`, then
update `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, and the frontend's
`VITE_API_BASE_URL`. Rebuild the frontend after changing its API URL.
