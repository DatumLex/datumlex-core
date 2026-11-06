# Civil liability ETL in DatumLex

The local ETL builds a searchable civil liability collection. The catalog
keeps case law, precedent references, and legal scholarship in separate
categories and records the source and content type of each item.

## Sources and collection scope

The configured court scope is STJ, TJDFT, TJSP, TJMG, TJRJ, TJRS, TJPR, TRF1,
TRF3, and TST. Actual coverage depends on each source and court.

| Source | Material collected | Default collection scope |
| --- | --- | --- |
| TJDFT JurisDF | Public judgments with eligible full text | Searches for `responsabilidade civil` across years from 2016 to the current year. Requests 25 results per page and budgets up to 1,000 results per batch. A full batch of full pages takes 40 requests. Short or empty pages can increase the request count. |
| Pangea | Precedent references and their source metadata | Searches for `responsabilidade civil` in the configured court scope, up to 10 pages of 100 results per run. |
| STJ and TST | Decision summaries (ementas) | The local ETL passes a collection limit of 400 to the summaries collector. |
| DJEN | Recent publications identified as appellate judgments | The local ETL passes a limit of 1,000 to the publications collector. Publication excerpts retain their own content type. |
| Open legal scholarship | Bibliographic records and accessible article files | Collects from the configured scholarship sources. Text is available for processing when extraction and verification succeed. |

Collection limits describe the configured workload. The count of new items
depends on source responses, eligibility checks, and duplicates.

## Topics

The catalog classifies collected items under ten initial topics. TJDFT and
Pangea use the broad query above by default.

1. Non-pecuniary damages
2. Pecuniary damages and full compensation
3. Healthcare
4. Traffic accidents
5. Improper credit reporting
6. Air transport
7. Real estate delivery
8. Image, honor, and privacy
9. Loss of chance
10. Internet-related liability

## Processing and recovery

1. **Extract and archive.** Collectors save source responses or documents
   with source identifiers, URLs, dates, and hashes when available. Paginated
   collectors save the archive and index before advancing their cursors.
2. **Validate and transform.** The offline processor verifies hashes,
   normalizes records, extracts available text, and handles duplicate
   inputs. The NLP pipeline produces candidate evidence for review, with
   the original source and text provenance retained.
3. **Load and index.** The processor imports records into the local
   database and refreshes the subject catalog. Precedent references,
   judgment summaries, full decisions, publication excerpts, and
   bibliographic records retain their respective content types.
4. **Recover from failures.** Invalid TJDFT responses leave their page
   pending for retry. Pangea records the stage of a collection failure and
   the page number when applicable. Previously archived Pangea pages can
   still be imported offline using their archived catalog metadata.

Use `scripts/run-etl.ps1 -Mode all -Once` for a complete local cycle or
`scripts/run-etl.ps1 -Mode process -Sources 'pangea' -Once` to process archived
Pangea input. See the [local ETL operations guide](../docs/operations/ETL-ELT-LOCAL.md)
for setup, execution modes, and log locations.
