# Resource dimensional schema (v2)

The backend adopts the dimensions and resource fact from `datumlex.session.sql`.
The executable schema is defined by Django models and migrations; the SQL file
remains the original design reference, not an installation script.

## Fresh data only

Migration `0002_resource_schema` drops and recreates the v1 warehouse tables,
including extraction history and movements. It does not convert or retain v1 data.
Reversing its schema operations cannot recover deleted rows.

The default SQLite file is now `data/datumlex_v2.sqlite3`. Docker Compose uses a
separate `datumlex_pg_v2` volume and database `datumlex_v2`, so existing databases
are not used or copied. A nonempty existing DATABASE_URL must be changed to the
new database before migrating. Do not apply this migration to another deployment
whose data should be retained.

## DataJud mapping

| Table | Source and identity |
|---|---|
| `dim_process` | Unique 20-character `numeroProcesso`, preserving leading zeros; public `secrecy_level=0` |
| `dim_degree` | Unique `grau` in `code_degree`; label currently equals the source code |
| `dim_class` | Unique `classe.codigo`, source label truncated to 100 characters |
| `dim_org` | Unique `(court, code_org)`; source organization and municipality code |
| `dim_subject` | Unique subject code; repeated/nested source subjects deduplicated |
| `dim_time` | Unique filing date (`dataAjuizamento`), stored in column `data` |
| `dim_result` | Stored output of the existing document-level classifier; `unknown` without dated evidence |
| `fact_resource` | One row per unique DataJud `source_id`, with FKs to all six dimensions and weight `quant_resource=1` |
| `fact_process_subject` | Unique `(id_resource, id_subject)` linking a resource document to its subjects |

Seven dimensions are present: process, degree, class, organization, subject, time,
and result. Subjects attach through the bridge; the other six attach to the fact.
Different documents/degrees can refer to the same process dimension. The physical
fact name does not establish that each DataJud document is a distinct appeal.
API `analyzed_appeals` remains unavailable; volume and merit rates retain their
document-level meaning.

## Necessary implementation adjustments

- Generated bigint IDs replace manually assigned integer IDs. Dimension source
  codes are unique business keys, separate from surrogate IDs.
- `fact_resource.id_resource` is the single primary key; `source_id` is unique.
  The reference's composite primary key is redundant once the resource ID is unique.
- The bridge references the fact directly instead of duplicating its class,
  process, organization, degree, time and result foreign keys. This prevents a
  subject association from disagreeing with its resource. It has a generated
  row ID plus the unique pair constraint.
- Absent municipality codes remain NULL instead of becoming invented IBGE codes.
  Process numbers use varchar(20), validated as exactly 20 digits before loading.
- `extraction_run`, `process_movement`, `rejected_record` and fact provenance fields
  remain as operational extensions for pagination, audit and evidence.
- The Python class `FactProcess` is retained for internal compatibility but maps
  to `fact_resource`. Existing API field names remain stable, including source
  class/subject codes rather than their new surrogate IDs.

Stored results follow `tpu-document-latest-v2`: granted, denied, partial,
not_admitted, partial_knowledge, unknown, ambiguous or outside_degree. The last
label maps to the API's existing `outside_appellate_degree` label to fit the
reference's 20-character limit. Classification is refreshed from movements in
the same transaction as the fact. Missing evidence never becomes granted/denied.
See `merit-methodology.md` for the classifier's limitations.

## Start PostgreSQL and fetch a fresh sample

In `backend`, set `POSTGRES_PASSWORD` in the ignored `.env`, and set
`DATABASE_URL=postgresql://datumlex:<URL-encoded-password>@127.0.0.1:5433/datumlex_v2`.
Use the current public CNJ key in `DATAJUD_API_KEY`, from
https://datajud-wiki.cnj.jus.br/api-publica/acesso/ .

```powershell
docker compose up -d --wait db
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py test tests
.venv/Scripts/python.exe manage.py extract_datajud --subjects 10431,10433,10439 --start 2023-01-01 --page-size 100 --max-pages 2
```

The sample contains at most 200 fetched documents. `paused` denotes the explicit
page limit, not complete coverage. Continue with the run ID printed by the command:

```powershell
.venv/Scripts/python.exe manage.py extract_datajud --resume <run-id> --max-pages 5
```

Each page and its cursor commit together. Repeated documents update rather than
duplicate facts. An older source version cannot overwrite a newer stored version.
Tests use a separate temporary database and synthetic fixtures; live imports do not.

## Dashboard queries

Statistics and distribution aggregate `dim_result` in SQL. The loader calculates
this result from the movement snapshot in the same transaction as the fact, so
dashboard requests do not reload every raw payload and movement. When changing
the classification rules, reclassify existing facts before serving the new rule
version; direct edits to movements must also refresh the stored result.

Subject filters use EXISTS to retain one row per document. Process pages exclude
raw payloads and prefetch only the movement fields needed for classification
evidence. The API contracts and the frontend's 20-second timeout are unchanged.

Local PostgreSQL validation with 22,746 documents found zero differences between
stored results and the latest-movement classification. Using Django's request
client, the scope request followed by the three concurrent dashboard requests
took 0.214 seconds for the full period and 0.360 seconds for a subject/year filter.
These timings exclude browser rendering and network latency. The 28-test suite
also passed, including summary deduplication, result refresh after import, and
checks that dashboard queries do not select raw payloads or movement rows.
