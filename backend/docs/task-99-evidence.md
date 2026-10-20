# Task #99 — auditable STJ ingestion

Issue: https://github.com/DatumLex/datumlex-core/issues/99

## Delivery and scope

The local implementation uses the official STJ publication catalog and official
JSON/ZIP resources for Civil Liability subject codes 10431, 10433 and 10439,
publication dates 2023-01-01 through 2026-10-15. The complementary DataJud STJ
pipeline retains filing-date semantics. Source texts are not analytical resource
facts and are not silently linked to CNJ processes.

Implementation and schema: `src/etl/stj_ingestion.py`, `etl/stj_documents.py`,
`STJDocument`, `STJDocumentVersion`, `STJIngestionRun`, `STJDocumentBatch`,
migration `0004_stj_audit_versions`. See the complete
[source-to-target mapping](../../etl/STJ-ARCHITECTURE.md).

This is a working-tree delivery based on core commit
`873cddec98bf1f666f3d5a6cc9bf9b1b8deb7047`; it is not a merged/reviewed release.

## Acceptance evidence

| Criterion | Implemented evidence |
|---|---|
| Pagination and rate limits | DataJud search-after cursor; STJ catalog enumerates dated publication resources; bounded HTTP retries for 429/5xx/network errors, numeric Retry-After, local request pacing |
| Recovery | Atomic per-batch counters/checkpoint; completed batches skipped; missing/invalid records kept pending; exclusive local collector lock; `--refresh` replays completed source batches |
| IDs and original URLs | `seqDocumento`, unchanged metadata, metadata and ZIP URLs; DataJud original payload and namespaced source key |
| Available text | Hash-addressed original TXT/PDF bytes; immutable old content paths; current path/hash plus version snapshot |
| Dates, panel, precedent type/status | Publication required, judgment date/panel/type/status nullable when absent; no inferred binding authority; original minister/type/registration fields remain in source metadata |
| Collection/version lineage | Run ID, collector version, timestamps, catalog hash, preserved catalog snapshot/license fields; document-version fingerprints include metadata, URLs, text hash and availability |
| Idempotency and updates | Tests cover same-document replay, changed text, metadata-only change, recovered unavailable text and preservation of already acquired content |
| Inaccessible records | Missing member or ZIP 403/404/410 produces explicit unavailable observation; other transient failures are retried; invalid rows are rejected with source ID/reason |
| Reconciliation and field coverage | `report_stj_ingestion --verify-files`: per-run counts, equation check, field availability, current records, versions, sample URLs and file integrity |

The source-observation equation is:
`retrieved = created + updated + duplicates + failed`.
`unavailable` is a subset of accepted observations and is not added again.
Counts refer to unique selected IDs within each publication batch; raw source
rows and selected rows are retained in the batch scope. Repeated runs are separate
observations; aggregate run totals must not be mistaken for distinct documents.

## Verification

62 automated Django tests passed using an isolated in-memory database and
synthetic source fixtures. The suite covers regression, integrity checks,
Retry-After, unavailable-to-available recovery, duplicate/version behavior,
publication/subject filters, archive path containment, legacy baseline backfill
and court separation. Ruff checks pass for changed modules; model migrations
match the models. No new UI behavior was introduced in this task increment.

The official 2023-01-03 batch was replayed twice to verify real-source
idempotency. Machine-readable results, field coverage, URLs and local integrity
are in [the reconciliation report](evidence/task-99-stj-reconciliation.json).
The first replay established 41 current versions; the second reported 41
duplicates, zero new documents, zero new versions and zero failures. A verified
local baseline added versions for 521 legacy documents. All 562 acquired texts
passed file/hash verification. The live catalog declared `cc-by` (Creative
Commons Attribution). The sampled structured metadata did not supply judgment
date, panel or precedent type/status; all four fields remain explicitly null.
The pending official 2023-01-17 batch was also replayed: 15 selected records,
11 acquired texts and 4 unavailable ZIP members. The missing IDs are persisted
with unavailable state and pending batch evidence, without discarding acquired
texts. These observations reconcile separately from the distinct-document total.
The `existing-local-snapshot` run verifies legacy text hashes and establishes a
current baseline; it does not reconstruct unrecorded historical versions.

From `backend/`:

```powershell
$env:DJANGO_SETTINGS_MODULE='config.test_settings'
../etl/.venv/Scripts/python.exe manage.py test tests --verbosity 1
```

Remove the test-settings variable before operating the real database. From a
fresh shell in `etl/`:

```powershell
.venv/Scripts/python.exe stj_documents.py --subjects 10431,10433,10439 --start 2023-01-01 --end 2026-10-15
```

For a reviewed refresh sample add `--refresh --max-batches 1`. Repeating the same
scope resumes pending batches. This local implementation currently uses Windows
file locking. Full-corpus extraction is separate from acceptance on a real sample.

## Source rights and coverage

The run stores the catalog's `license_id`, `license_title`, and `license_url` as
returned, including null when unavailable; no broader rights are inferred. Use
the original official source URLs and retain attribution. A metadata catalog does
not prove full-text availability or grant blanket redistribution rights.
The real sample's observed license and missing field counts are in the report.

Source availability is disclosed per publication batch; the requested end date
does not invent resources absent from the official catalog. Partial batches do
not prevent processing other dates, and the final status is PARTIAL while source
files or validation issues remain unresolved. Unknown panel, precedent type or
status remains null. The collector does not decide whether a decision binds TJDFT.

## Handoff and completion boundary

The persisted models and versioned local text paths are available to downstream
#105, #109 and #111; cross-source matching and NLP are not implemented here.
Source and dictionary/model changes are documented for review. User instruction
authorized this implementation but does not constitute independent model review.

Formal **Done** remains dependent on recorded review of #98/#104 inputs, an
independent review of this delivery, the shared PR/CI evidence and any required
environment acceptance under the team's DoD. This document does not close #99,
mark acceptance checkboxes on GitHub, or claim deployment to Railway/Vercel.
