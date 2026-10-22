# BDJur feasibility — 2026-10-21

Task #101, parent #100. Bounded investigation: six direct requests and three
indexed official item records. **Research findings for review; ingestion blocked.**

## Reproduction and observed access

```text
python backend/docs/probe_bdjur.py --output NEW_REPORT_PATH.json
```

The credential-free probe records URL, UTC observation time, HTTP status and
content type. It never overwrites earlier evidence, retries denied requests,
solves challenges, downloads source text, or writes to an application database.
The [captured run](evidence/task-101-bdjur-access-2026-10-21.json) returned **403
for all six requests**: homepage, robots.txt, API root and three item routes.
The in-app browser independently displayed the STJ automatic security
verification page. This is an access limitation in the tested environment,
not proof that BDJur is generally offline or inaccessible to every user.

No working search/API pagination contract, API authentication requirement,
published rate limit or machine-harvesting permission was verified. A 403 is
not evidence of a documented request quota. Do not bypass the protection or
silently reuse a browser session for an automated collector.

## Official source findings and bounded candidate sample

The [STJ library page](https://www.stj.jus.br/sites/portalp/Institucional/Educacao-e-cultura/Biblioteca/BDJur-e-Consorcio-BDJur)
identifies BDJur and distinguishes restricted items. It does not establish a
general license for automated collection or redistribution.

The following **indexed official metadata** was available through web search.
Its index age differs by record; these observations are not fresh live API
retrieval, verified PDF contents or an ingested/approved analytical corpus.

| Stable handle | Title / author | Publication value | Observed metadata |
|---|---|---|---|
| [2011/75016](https://bdjur.stj.jus.br/entities/publication/67297921-a874-4880-b8e5-e65e235d4338) | A responsabilidade civil do Estado por omissão e suas excludentes — Eugênio Rosa de Araújo | 2011 and 2018 | Open-access collection label; two PDF filenames and bibliographic citations |
| [2011/73419](https://bdjur.stj.jus.br/entities/publication/4bd0920d-0f94-4736-b099-78ddcac45022/full) | Direito autoral e responsabilidade civil — Sergio Cavalieri Filho | 2001 | Title, author, subjects, citation, language, stable URI, PDF filename and submission-license attachment listing |
| [2011/69290](https://bdjur.stj.jus.br/items/9431076b-d413-4887-b648-4c346b35fda4) | O avanço da responsabilidade civil sob a ótica da perda da chance — Rodrigo Sergio Gomes Bitencourt | 2013 | Open-access collection label, author, citation and PDF filename |

Useful indexed title/author/date/identifier/link coverage: **3/3 candidates**.
Multiple publication dates: **1/3**; do not select one date arbitrarily.
Verified live metadata responses: **0/3**. Acquired or integrity-checked source
texts: **0**. Verified reusable full-text licenses: **0**. This small relevance
sample is not a census, a legal equivalence assessment or post-2023 coverage.

## Access and rights boundary

An open-access collection label describes access; the inspected metadata does
not itself establish permission for this project's full-text reuse. The second
record lists a submission-license file, but its contents were not obtained.
No Creative Commons license or equivalent downstream permission is assumed.
Keep candidates metadata-only, outside approved indicators and production
ingestion, until the source/model owner reviews access, permitted use and rights.

Recommended next research boundary: these three stable handles only. Obtain
authorized reproducible access and the item-specific rights/terms; measure
metadata versus readable/permitted text; preserve original publication precision,
all dates, identifiers, collection and license evidence. Preserve unavailable
states rather than inventing full text from metadata.

All three candidates predate 2023. The initial DataJud filing-date scope cannot
silently become a doctrine publication-date rule. Resolve historical doctrine
as contextual support versus date-filtered search with #104/#165 and the PO
before admitting a corpus. Similar subject wording supplies a candidate thematic
association only; it proves neither legal agreement nor precedent adherence.

## Dependency and decision record

- #101: negative access findings and candidate metadata are ready for independent
  review. No successful connector or full-text sample is claimed.
- #104/#102: need verified source/target and rights contracts, a live reproducible
  sample, and a reviewed date/version policy. #102 is already closed on GitHub;
  closure is preserved and does not substitute for missing source evidence.
- #105/#109/#111: no approved BDJur text, matching or annotation material is
  supplied by this investigation. Existing STJ material is a separate source.
- PO/source owner: decide how to obtain authorized access and document permitted
  reuse/date scope. No request was sent to a third party, no source was replaced,
  and no production/data/credential configuration was changed.

Validation: the six-observation report parses as JSON; every URL remains an
official BDJur HTTPS route; the probe passed Ruff. Independent source/rights
review and actual collection remain outstanding. A negative feasibility result
may complete research after review; it cannot complete dependent ingestion.
