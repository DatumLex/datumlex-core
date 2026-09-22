# DatumLex frontend

Update 18/09/2026: the cards and charts display API-calculated rates per document, based on the binary dataset and visible exclusions. Refer to the [current methodology](../backend/docs/merit-methodology.md). This replaces previous "merit unavailable" notes; an empty dataset continues to display “—”.

React dashboard built with Vite and Tailwind CSS.

## Development

```bash
npm install
npm run dev
```

Use Node >=22.12 (or a supported version matching Vite's engine requirement).
Start the Django backend on `127.0.0.1:8000` using `../backend/README.md`.
Vite forwards `/api` to that backend; no frontend secrets or API key are needed.
For another environment, set `VITE_API_BASE_URL` (see `.env.example`) and configure
the backend's allowed origins. Restart Vite after changing environment variables.
The production build requires that URL or a host reverse proxy; Vite's development
proxy is not included in static build output.

The dashboard loads scope, statistics, distribution availability and quarterly
instance counts. Date controls use the loaded range and filter by filing date.
Apply/reset fetch real data; interrupted requests cannot overwrite newer filters.
Loading, empty, partial-sample and error/retry states are explicit.

The first card counts DataJud documents, not analyzed appeals. Merit rates remain
unavailable because the backend does not yet classify appeal results. Outcome
filtering remains unavailable for the same reason. All loaded degrees, including
JE, appear in the chart and accessible table so counts reconcile with the API.
The fixed subject describes the current Civil Liability extraction; this view
assumes that local warehouse scope and does not imply full subject coverage.

Validation: `npm run lint` and `npm run build`. With both servers running, the
browser integration test uses Playwright and installed Microsoft Edge:

```powershell
# Point to an available Playwright module, or install Playwright separately.
$env:PLAYWRIGHT_MODULE = '<absolute-path-to-playwright/index.mjs>'
node tests/integration.mjs
```

It compares real API/UI totals and filters, then simulates empty/error/stale
responses without modifying the database. It also checks 320px layout and the
accessible data table. Requires a populated local backend.
