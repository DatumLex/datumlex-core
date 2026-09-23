# Historical v1 implementation dictionary

Superseded on 2026-09-22 by [the v2 resource schema](resource-schema.md), which
documents the current tables, columns, source mapping and fresh-data transition.
The descriptions below are retained only as history of the removed v1 schema.

Update 2026-09-18: grant_rate and denial_rate are nullable fractions calculated at document grain by `tpu-document-v1`; binary_denominator counts eligible documents, and excluded contains exclusion counts. Process responses include mapped outcome, evidence codes/dates and rule_version. No schema migration or appeal-grain fact was introduced. See [current methodology](merit-methodology.md), which supersedes earlier unavailable-rate notes below.

Reference: `documentation/architecture/Dimensional-Model.md` (main d3492f3).
This is an implementation proposal and local executable schema, not independent modeling approval.
The schema source of truth is `src/db/models.py` and `src/db/migrations/0001_initial.py`.

## Grain and changes to the reference

One `fact_process` row represents one DataJud document, identified by `_id` (fallback `id`).
It is not one appeal, judgment or CNJ process across all degrees. `quant_process` is constrained
to 1. All aggregates count distinct fact IDs; the subject bridge cannot multiply measures.

- `number_process` is text, preserving the 20 digits and leading zeroes; never Bigint.
- A surrogate fact PK replaces the ambiguous multi-column physical key. Time/class/org are FKs,
  while `source_id` is the idempotent unique business key.
- Organization identity includes court + source organization code.
- Time means filing date, explicitly separate from judgment and update dates.
- Added ingestion runs, rejected-record metadata and deduplicated movements for auditability.
- No appeal outcome entity or classification rule is invented. This is the process-volume
  foundation. An independently reviewed appeal grain, source evidence and classification
  versioning are required before introducing merit measures.

## Tables and fields

Unless specified, columns are required (NOT NULL). Unspecified IDs are generated BigAutoField
primary keys. Foreign keys use PROTECT unless child-lifecycle deletion is explicitly stated.
Empty name strings mean the code exists but its source label is unavailable; codes are never invented.

| Table | Fields, types and constraints | Origin / meaning |
|---|---|---|
| `dim_time` | `id` bigint PK; `date` date UNIQUE; `year`, `month`, `day`, `quarter` positive smallint | Parsed `dataAjuizamento`; quarter = floor((month-1)/3)+1 |
| `dim_class` | `code` positive int PK; `name` varchar(255) | `classe.codigo`, `classe.nome` |
| `dim_org` | `id` bigint PK; `court` varchar(16); `code` positive int; `name` varchar(255); `municipality_code` varchar(16), empty allowed; UNIQUE(court, code) | `tribunal`, `orgaoJulgador.codigo/nome/codigoMunicipioIBGE` |
| `dim_subject` | `code` positive int PK; `name` varchar(255) | Flattened `assuntos.codigo/nome`; unique codes per source record |
| `fact_process` | `id` bigint PK; `source_id` varchar(255) UNIQUE; `number_process` varchar(32); `court`, `degree` varchar(16); `secrecy_level` positive smallint default 0 | `_id`/`id`, string `numeroProcesso`, `tribunal`, `grau`, public-only scope |
| `fact_process` | `time_id`, `process_class_id`, `organization_id` FKs; `quant_process` positive smallint default 1 CHECK=1 | Filing date, class and organization references; one document weight |
| `fact_process` | `source_updated_at`, `source_timestamp` nullable datetime; `collected_at` datetime auto-updated; `last_run_id` FK | `dataHoraUltimaAtualizacao`, `@timestamp`, local collection clock, ingestion provenance |
| `fact_process` | `raw_payload` JSON; `payload_hash` varchar(64) | Allowlisted original metadata; SHA-256 of canonical JSON; ignored database only |
| `fact_process_subject` | `id` bigint PK; `process_id` FK CASCADE; `subject_id` FK PROTECT; UNIQUE(process_id, subject_id) | Many-to-many bridge; repeated/nested subjects deduplicated |
| `process_movement` | `id` bigint PK; `process_id` FK CASCADE; `fingerprint` varchar(64); `code` nullable positive int; `name` varchar(512); `occurred_at` nullable datetime; `complements` JSON default []; UNIQUE(process_id, fingerprint) | Movement code/name/date and tabulated complements; hash of normalized content |
| `extraction_run` | `id` bigint PK; `started_at` auto datetime; `finished_at` nullable datetime; `status` varchar(24) default running; `scope` JSON; `cursor` nullable JSON | Exact query scope and last committed `search_after`; statuses running/paused/failed/completed/sample |
| `extraction_run` | `pages`, `fetched`, `created`, `updated`, `rejected`, `stale` positive int default 0 | Cumulative page/record counters, including resumed invocations |
| `extraction_run` | `source_total` nullable positive bigint; `source_total_relation` varchar(8), empty allowed; `error` text, empty allowed | Source-reported total and eq/gte relation; sanitized failure description |
| `rejected_record` | `id` bigint PK; `run_id` FK CASCADE; `source_id` varchar(255); `reason` varchar(255) | Traceable validation failure without retaining rejected source contents |

Index: `fact_process(court, degree, time_id)`, plus database indexes for keys and FKs.
Positive-code validation occurs before ORM loading. Degree domain: G1, G2, JE, TR, SUP.
Nullable source dates/movement codes remain absent; they do not become an invented timestamp/code.
Malformed supplied dates or codes reject the record instead of silently normalizing to a false value.

## Load and recovery semantics

Dimensions load before facts, then bridges/movements. Each page and its cursor commit together.
Replaying a source document updates its row and replaces its subjects/movement snapshot. An older
source update cannot overwrite a newer stored document. Missing incoming update time cannot overwrite
a dated document. Dimension names follow the latest accepted record, not historical SCD versions.

`fetched = created + updated + rejected + stale`. `updated` includes idempotent replays;
it is not a count of changed payloads. Source totals can change while paginating. The warehouse
retains accepted records when later source records disappear or become confidential; therefore
source deletion/restriction synchronization remains required before any public deployment.
Run status `completed` means the pagination ended, not every record passed validation.
Always inspect `rejected`, run scope and source total. Raw data is internal to the local DB;
the API exposes only normalized metadata and source IDs (which can contain process identifiers).

SQLite and PostgreSQL share ORM/migrations. PostgreSQL execution must be verified on a running
server; passing SQLite tests does not prove PostgreSQL integration.
