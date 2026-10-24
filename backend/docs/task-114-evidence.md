# Task #114 — versioned NLP evidence

Local implementation, 2026-10-23. No deployment or independent review is implied.

## Scope and model

Consumes the actual `src.nlp` output contract `0.1.0` from #109. It preserves
the full original result, including pipeline/model/rule/prompt metadata,
confidence, uncertainty, coverage and missing-source warnings. The importer
verifies the artifact through the #109 reader and verifies the output checksum.

`NlpDocument` identifies a source document (not a process or an analytical fact).
`NlpTextVersion` stores immutable exact text, UTF-8 hash, representation and source
metadata (original URL, source version, artifact hash/location when supplied).
`NlpSourceObservation` records successive availability checks using a per-document
sequence; timestamps alone do not reliably order rapid observations on Windows.
`NlpExtraction` stores each result/attempt and optional preceding execution/reason.
`NlpEvidence` stores individual original annotations. `NlpRevision` stores a
complete before/after payload, action, sequence, protected reviewer FK, timestamp,
reason and request hash. `NlpSnapshot` freezes selected evidence projections for
downstream UI/PDF consumers. None of these rows contributes to `fact_resource`.

Source/text metadata share a text-version row in this initial physical model.
There is no separate generalized artifact store yet. Existing STJ tables are
not rewritten or silently backfilled. Source changes must produce new versions;
previous extraction/review records remain reachable by their IDs.

All new tables reject UPDATE and DELETE at database level. PostgreSQL additionally
rejects TRUNCATE and validates revision sequence, previous payload, transition,
immutable machine fields and exact text spans. Runtime credentials must not own
the tables or have DDL/superuser privileges: a database administrator can disable
triggers. This is operational audit protection, not a cryptographic ledger.

## Installation and ingestion

Use the project's configured database and normal deployment migration process:

```powershell
../etl/.venv/Scripts/python.exe manage.py migrate
../etl/.venv/Scripts/python.exe manage.py import_nlp_result PATH_TO_RESULT.json --root PATH_TO_WORKSPACE --request-key UUID
```

Use the same request UUID only for a technical retry of the same command.
For intentional reprocessing, use a new UUID and supply `--previous-id UUID
--reason "Reason"`. The same UUID with different output/lineage is a conflict.
Failed/missing-text results are stored without fabricated evidence. All insertions
for an execution are atomic. Import performs no network requests.

Migrations `0010` and `0011` are additive. Do not reverse `0010` on a populated
deployment: that deletes history. Operational rollback means reverting readers
and stopping ingestion while retaining these tables. `0011` has an administrative
reverse operation for controlled maintenance, which deliberately removes guards.

## Review contract

Session authentication, account approval, password-change and CSRF rules remain
active. Read access requires the document court. Review writes additionally require
Admin/Master (provisional product policy). Reviewer and timestamp come from the
server, never from the request. Support-account behavior follows existing policy.

States: `pending`, `corrected`, `approved`, `rejected`.
Pending can approve/correct/reject; approved and corrected can correct/reject/reopen;
corrected can also approve. Rejected can only reopen. Reopen preserves values and
returns to pending. Corrected is not independent legal approval.

```http
POST /api/v1/evidences/{uuid}/revisions/
Idempotency-Key: <uuid>
Content-Type: application/json

{"expected_revision":0,"action":"approve","reason":"Checked against source"}
```

Correction adds `replacement`, a complete annotation. Annotation ID, machine method,
confidence, automatic label/review fields cannot be rewritten. Human review status
is returned separately. Corrected spans must still equal the SAME immutable text.
OCR/text corrections require a new text version and extraction. Offsets are zero
based Unicode code points, `[start,end)`. JavaScript UTF-16 offsets require conversion.
`Não houve nexo causal.` has 22 code points, not 21.

Stale base revisions or mismatched idempotency keys return HTTP 409. Malformed
payloads return 400, forbidden scope 403 and missing IDs 404. The evidence row is
locked for the entire review transaction; independent database connections cannot
silently overwrite each other.

## Reads for #115 / #129

```text
GET /api/v1/extractions/{uuid}/                    full unchanged #109 result
GET /api/v1/extractions/{uuid}/evidences/?limit=50&after=ANNOTATION_ID
GET /api/v1/evidences/{uuid}/?view=original        original annotation, revision 0
GET /api/v1/evidences/{uuid}/                     latest effective revision
GET /api/v1/evidences/{uuid}/?revision=1           exact historical revision
GET /api/v1/evidences/{uuid}/revisions/?limit=50&after=0
POST /api/v1/evidence-snapshots/
GET /api/v1/evidence-snapshots/{uuid}/
```

Snapshot request: `{"evidence_ids":["UUID"],"context":{"court":["STJ"]}}`.
Up to 500 explicit, unique evidence IDs, in caller-selected order. The snapshot
stores the actual selected revision IDs, values, source observation IDs, pipeline
versions and exact supporting passages. It has its own SHA-256 and timestamp.
Review/source changes do not change it. Reads recheck current authorization and
owner identity. #129 should render this persisted JSON, not query latest reviews.

Live extraction pages sort by immutable annotation ID; they do not claim a legal
ranking. Review values may change between live pages, so use a snapshot for stable
exports/comparison. A rejected annotation remains audit-accessible; consumers must
apply their approved inclusion policy rather than interpreting visibility as approval.

The supplied context is explicitly marked `caller_supplied_pending_165`; this
endpoint does not claim to validate analytical filters or calculate legal metrics.
The returned count is evidence count, never process/appeal count. The whole PDF
renderer and React cards belong to #129/#115 and are not implemented here.

Source observations distinguish available, changed, not_found, removed,
temporarily_unavailable and restricted. A 404 is not automatically a confirmed
removal. `observe_source` records a supplied observation; it is not a crawler.
The API preserves source warnings from #109 instead of inventing missing URLs.

## Verification

```powershell
../etl/.venv/Scripts/python.exe -B manage.py test tests.test_nlp_evidence --settings=config.test_settings
# DATABASE_URL must point to an isolated local PostgreSQL server with CREATEDB.
$env:NLP_REAL_ROOT = 'PATH_TO_WORKSPACE'
../etl/.venv/Scripts/python.exe -B manage.py test tests.test_nlp_evidence --settings=config.postgres_test_settings
```

`postgres_test_settings` creates a uniquely named `test_datumlex_*` database and
removes it. The concurrency test uses two connections and only disables TRUNCATE
guards during administrative teardown, with a test-database-name check. Normal
application code never disables guards. SQLite cannot prove PostgreSQL concurrency.

Local real-output reconciliation on 2026-10-23: 30 #109 outputs (8 TJDFT, 22 STJ),
360 annotations, original checksums/values and source texts retained. These are
engineering checks, not legal validation or model-quality approval. Existing
warnings/rights limitations remain visible. `NLP_REAL_ROOT` enables this optional
test; it is skipped in CI when local source artifacts are unavailable.

Final local verification: all 106 backend tests passed against PostgreSQL 17 in
an isolated container (40.703 seconds), including the 20 task-specific tests,
two-connection concurrency and real-output reconciliation. Ruff 0.16.8 passed
for all changed Python files; `makemigrations --check --dry-run` found no drift.
The test container was disposable. No migrations were applied to the project's
normal database, and no Git/GitHub operations were performed.

## Outstanding architecture/acceptance decisions

- Independent review of #104 grain, dictionary and source mapping is still needed.
- #109 v0.1.0 rejects relations and supports TJDFT/STJ; no invented BDJur adapter.
  Approved BDJur material and a versioned contract extension are prerequisites.
- Confirm reviewer roles, independent adjudication and inclusion of corrected items.
- Define #165 canonical analytical context, denominators and approved ranking policy.
- Complete direct official URLs where the current #109 outputs flag them missing.
- Approve durable artifact retention, storage rights and removal/redaction policy.
  API reads must not be enabled for a corpus lacking the required rights approval.
- Validate #115 UI and #129 PDF against these snapshots, and obtain independent
  implementation review before claiming the GitHub task accepted/production-ready.
