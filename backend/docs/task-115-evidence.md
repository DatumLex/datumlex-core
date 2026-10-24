# Task #115 — explainable NLP API and dashboard

Local implementation. No deployment, independent legal review, GitHub acceptance,
source-rights approval or #112 quality release is implied.

## Implemented boundary

Django/PostgreSQL readers consume the append-only #114 models. React/JavaScript
and Tailwind retain the approved shared dashboard, Portuguese UI and design
palette. No migrations or writes to the normal database are needed for the code
delivery. Runtime snapshot creation does insert an append-only `NlpSnapshot`.

Canonical #165 parsing is implemented for these v2 consumers. The existing
DataJud endpoints remain single-contract readers. The NLP panel inherits the
applied court/date/subject scope, with visibly local source/outcome controls.
This is not completion of the full #166/#167 migration of all dashboard panels.
Dates have typed meanings: filing dates in DataJud, decision dates in decision
texts, reviewed validity for authorities, publication dates for doctrine.

## API

All endpoints require an approved, active session; writes require CSRF. Court
sets are authorized in full. Support behavior follows existing account policy.

| Method and path | Contract |
|---|---|
| GET `/api/v2/filter-options/` | Canonical context/defaults, authorized courts, source availability and mapped/released counts |
| POST `/api/v2/analysis-snapshots/` | Body `{"context": {...}}`; resolves defaults, validates scope and freezes result |
| GET `/api/v2/analysis-snapshots/{uuid}/` | Manifest, populations, coverage, quality and immutable SHA-256 |
| GET `/api/v2/analysis-snapshots/{uuid}/theses/` | Paginated literal thesis groups |
| GET `/api/v2/analysis-snapshots/{uuid}/grounds/` | Paginated literal ground groups |
| GET `/api/v2/analysis-snapshots/{uuid}/{theses-or-grounds}/{group}/sources/` | Exact selected #114 evidence projections |
| GET `/api/v2/analysis-snapshots/{uuid}/export/` | Complete frozen JSON, including all pages and evidence |
| GET `/api/v2/analysis-snapshots/{uuid}/report/` | Escaped, accessible HTML report with print CSS and browser Save as PDF |

Array queries use repeated `court[]`, `outcome[]`, `source[]` keys. A single blank
array value means empty; omission means defaults. Mixed blanks, unknown fields,
repeated scalars, invalid dates and unauthorized complete court sets are rejected.
Dates run from 2023 to today's date in America/Sao_Paulo. Subject query is one
explicit code; JSON context uses `subject_codes`. Arrays are sorted/unique.
OR within dimensions, AND across applicable dimensions. Filter identity is SHA-256
of the canonical, explicit JSON, independent of pagination/order.

Example request (identifiers are not claims of source availability):

```json
{
  "context": {
    "contract_version": "analytical-context-v1",
    "courts": ["STJ", "TJDFT"],
    "sources": ["stj_jurisprudence", "tjdft_jurisprudence"],
    "outcomes": ["denied", "granted"],
    "subject_codes": [10433],
    "start": "2024-01-01",
    "end": "2024-12-31"
  }
}
```

List query: `population=decision_text|precedent|doctrine`,
`order=-document_count|document_count|label`, `limit=1..100` (default 20), optional
signed opaque `cursor`. Source pages accept `order=evidence_id` only. Cursors bind
snapshot, population, resource, group and order; they cannot cross contexts.
Text ordering uses Python Unicode code-point ordering; ties use group ID.
`total_items` is group/evidence count for that endpoint, never process count.

Responses expose `snapshot_id`, `query_id`, `items`, `order`, `total_items`,
`next_cursor`. Manifest populations expose `documents_in_scope`,
`documents_with_text`, `documents_processed`, `documents_quality_released`,
`denominator`, counting unit, period field and filter applicability. Unmapped
documents are disclosed separately: their analytical membership cannot be inferred.

Errors: 400 invalid contract/cursor; 401 unauthenticated; 403 scope/owner/release
revocation; 404 absent snapshot/group; 409 expired snapshot/capacity; 503 database
failure. Default TTL is 24 hours (`NLP_DASHBOARD_TTL_HOURS`). Expiry never silently
re-runs a query. A new refresh creates a new snapshot; POST is not an idempotent
review command and does not claim Idempotency-Key support.

## Ranking and quality

`distinct-document-exact-literal-v1`: group the exact sequence of stored passages
and label; count unique source document IDs. Repeated passages, subjects and
reprocessing attempts do not inflate document count. Five passages in one document
are one document and five evidences. Semantic equivalents are not merged; opposite
propositions and different speakers must not be inferred equivalent. No automatic
thesis-ground relationship is created: #109 v0.1.0 does not support relations.

The share denominator is the typed, quality-released document population after
the decision outcome display selection. Population counts before that selection
remain visible. Zero denominator yields null, never zero probability. Doctrine
and authorities do not use decision outcomes; their counts never increase DataJud
facts or appeal counts. Groups may overlap and shares need not total 100%.

Only human-approved effective annotations are included. Pending, rejected and
corrected-without-approval annotations are excluded and counted. Confidence and
machine provenance remain unchanged. A null score means unavailable, not zero or
low confidence. Explicit `low_confidence` warnings appear in source cards.

No thresholds are invented. Runtime defaults keep live NLP unavailable until
reviewed mappings and #112/source-rights release decisions exist. Configure two
server-owned settings through the application's reviewed settings/deployment
process (there is deliberately no browser/admin write endpoint):

- `NLP_DASHBOARD_CATALOG`: source document key -> exact `extraction_id`,
  `text_version_id`, source identifier, subject codes, typed date/outcome, title,
  `mapping_approval_reference`, and `release_id`.
- `NLP_DASHBOARD_RELEASES`: release ID -> `state=released`,
  `approval_reference`, `benchmark_version`, `rights_approval_reference`, exact
  pipeline JSON fingerprint, source, `inclusion_policy=human_approved_only`, and
  tasks `[LEGAL_GROUND, LEGAL_THESIS]`.

These settings carry references to the real reviewed decisions; entering strings
does not establish their validity. Operational review must verify the referenced
report, metrics, strata and thresholds. Missing/mismatched bindings block output.
Current #109 output is not evaluated; this implementation does not approve it.
BDJur has no approved #109 adapter/corpus in this delivery and stays unavailable.
Authority validity needs #118's reviewed temporal approval in its mapping.

Release bindings are frozen and rechecked on every read, export and report,
including reads through the older #114 snapshot route. Revocation overrides old
access. Historical review changes do not mutate an already frozen result.

## Evidence and PDF fidelity

Snapshots retain original/effective annotations, exact revisions, document/text/
extraction IDs, UTF-8 hashes, pipeline versions, source observation, coverage and
warnings. Exact Unicode `[start,end)` spans are checked against immutable text
before inclusion. No OCR repair or quote reconstruction is performed by readers.
HTML/React escape text, preserve whitespace and separate disjoint segments.
Unknown page location remains unknown. Direct official HTTPS links are restricted
to STJ/TJDFT domains; absent links are not replaced by homepages.

Print reports render the complete persisted payload, not a paginated browser
list or latest revisions. They include context/query/hash, all rankings, all
supporting passages, versions, missing-link and coverage limitations. Browser
print CSS supports A4 and Save as PDF. This is a local print handoff for #129,
not a claim that its separate server-side PDF feature has been accepted.

## Interaction and verification

The panel distinguishes loading, network failure/retry, explicit empty selections,
no released occurrences, partial corpus, unavailable quality/source and explicit
low-confidence warnings. AbortController and immutable request keys suppress stale
responses. Native fieldsets/checkboxes/selects, expanded-state buttons, live status,
focus after pagination, visible navy focus and ordinary links support keyboards.
Source expansion preserves focus and active context. Responsive checks cover
320/760/1000/1440 px and enlarged text. No color-only state or legal authority
inference from green/gold is added.

Reproducible checks from `backend/`:

```powershell
../etl/.venv/Scripts/python.exe -B manage.py test tests.test_nlp_dashboard --settings=config.test_settings --noinput
# Uses a uniquely named, disposable test_datumlex_* database:
../etl/.venv/Scripts/python.exe -B manage.py test tests --settings=config.postgres_test_settings --noinput
```

From `frontend/`, with supported Node >=22.12 and the local Vite test server on
127.0.0.1:5179:

```text
node tests/nlp-dashboard.mjs
node node_modules/eslint/bin/eslint.js src/NlpPanel.jsx src/nlpApi.js src/App.jsx
node node_modules/vite/bin/vite.js build
```

Fixtures `FX115-PERSISTED-01` and `FX115-BROWSER-01` are synthetic and explicitly
labelled. The former reconciles hand counts and #114 database records; the latter
mocks HTTP only for UI checks. No synthetic records are seeded in the normal DB.
Setting `NLP_REPORT_QA_DIR` to an existing artifact directory during backend tests
saves the exact report and snapshot for browser/PDF reconciliation. The browser
check uses the same directory plus `NLP_QA_PYTHON` (Python with pypdf), renders PDF
in memory and checks query/hash/text version/quote equality. Optional screenshots
are QA artifacts, not production examples.

Remaining acceptance inputs: independent API/model/legal review, actual #112
release decision, approved document/source mappings, complete #166/#167 shared
context migration, #129 acceptance, real released-source browser examples and
deployment evidence. They cannot be inferred from passing fixture tests.

## Local verification record — 2026-10-23 (São Paulo)

- Full PostgreSQL suite: 126 tests passed, no skips, in an isolated Django-created
  `test_datumlex_*` database; the normal database was not migrated or populated.
- Real-output reconciliation: 8 TJDFT + 22 STJ documents, 360 annotations.
  This establishes persisted-output fidelity, not legal/model-quality approval.
- Twenty #115 tests cover hand counts, duplicate passages/subjects, authorization,
  missing mappings/releases, pipeline mismatch, frozen corrections, signed
  pagination, expiry, legacy-route revocation, exact report and export context.
- Browser fixture passed source fidelity, keyboard expansion/pagination focus,
  null and low-confidence display, source changes, empty/error/unavailable states,
  aborted/stale requests, JSON download, 320/760/1000/1440 px and enlarged text.
- Actual Django report rendered in Chromium; PDF was checked in memory with
  pypdf for snapshot/query hashes, text version and the exact accented quotation.
  Screenshots were inspected under `output/task-115/`.
- Ruff, frontend ESLint, Vite production build and migration-drift check passed.
  Playwright is a development dependency; a compatible transitive Zod update
  leaves npm audit with zero vulnerabilities at verification time.
- No Git operations, commits, GitHub writes or production deployment were made.

## Interactive local demo

`scripts/run_nlp_demo.py` starts a loopback-only API on 8015 using the separate
`output/task-115-demo/synthetic.sqlite3` database. It executes the actual #109 rule
extractor on three synthetic texts (six annotations), persists #114 records and
uses explicitly simulated review/release bindings. There is no LLM or legal
release. Session and CSRF cookies have separate demo names.

With that script running, launch `node scripts/start-nlp-demo.mjs` from frontend
and open `http://127.0.0.1:5180/nlp-demo.html`. This dedicated entry authenticates
only the local synthetic demo account and renders the real `NlpPanel` against the
actual API, without HTTP mocks. `node tests/nlp-live-demo.mjs` verifies the journey.

On the user's subsequent request to run the system, additive migrations 0010 and
0011 were applied to the normal local database to repair missing NLP tables.
The normal database still had zero NLP extractions at that check; synthetic demo
records were not inserted there. Normal backend/frontend run on 8000/5173.
