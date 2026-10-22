# Canonical analytical context — proposal v1

Task #165, parent #164. Status: **proposed for independent API/model/UI/PDF review**.
This specification preserves the September 25 client requirement and the current
document-grain methodology. It does not approve a source, legal classification,
quality threshold, schema migration, or implemented endpoint.

## Compatibility and ownership

The existing `/api/` endpoints accept one court/outcome and reject repeated
parameters. They remain unchanged in this delivery. #166 should introduce a
versioned contract (proposed `/api/v2/`) after review, sharing one parser and
query policy across all consumers. #104 reviews source/record cardinality;
#118 owns legal eligibility; #112 owns NLP quality. Neither a proposed contract
nor synthetic examples satisfy their acceptance conditions.

## Request and canonical representation

HTTP query arrays use repeated bracketed keys, e.g.:

```text
court[]=TJDFT&court[]=STJ&outcome[]=granted&outcome[]=denied&source[]=datajud&subject=10433&start=2023-01-01&end=2026-10-21
```

URL encoding of brackets is equivalent. Comma-separated values, alternate array
keys, unknown fields, repeated scalars and malformed dates return 400. Values are
case-sensitive identifiers; whitespace is not silently repaired. Canonical JSON:

```json
{
  "contract_version": "analytical-context-v1",
  "courts": ["STJ", "TJDFT"],
  "outcomes": ["denied", "granted"],
  "sources": ["datajud"],
  "subject_codes": [10433],
  "start": "2023-01-01",
  "end": "2026-10-21"
}
```

Arrays are unique and sorted by identifier/code; request order is immaterial.
Dates are inclusive calendar dates, from 2023 through the server's current date
in `America/Sao_Paulo`. Datetime boundaries must be translated using each source's
documented timezone, never the browser timezone. Reversed/future/invalid dates
return 400. Pagination and presentation order are not part of filter identity.

| Field | Domain | Omitted live-request default | Explicit empty selection |
|---|---|---|---|
| `court[]` | TJDFT, STJ, each independently authorized | Available supported courts authorized for the session | Empty court set; no court-bearing records |
| `outcome[]` | granted, denied, partial, not_admitted, partial_knowledge, ambiguous, unknown, outside_appellate_degree | All categories in the configured current classifier | Empty displayed outcome set; population rates remain unchanged |
| `source[]` | datajud, tjdft_jurisprudence, stj_jurisprudence, stj_precedent, bdjur_doctrine | Available configured sources, with access/rights states disclosed | Empty source set; no records or applicable rates |
| `subject` | One exact approved Civil Liability code | Explicit initial set 10431, 10433, 10439 | Blank scalar is invalid |
| `start`, `end` | YYYY-MM-DD | 2023-01-01 and today's São Paulo date | Blank scalar is invalid |

An array is empty only when represented as one blank value (`court[]=`), or `[]`
in captured JSON. Mixing blank and nonblank values is invalid. Omission is never
interpreted as empty. Deduplicate valid values. Unknown identifiers return 400;
known-but-unavailable sources are retained in context and reported unavailable,
never substituted. All resolved defaults are returned explicitly and frozen for
subsequent navigation; newly loaded data must not silently add selected values.

Subject codes are an explicit initial policy, not automatic descendants. A
co-occurring subject does not establish a new approved practice area. Any new
code/policy version requires source/model review. The UI shows Civil Liability
and actual coverage; it must not imply Consumer Law or Contracts availability.

Clear/reset restores the server's returned default context, including dates,
and atomically refreshes all panels. Clearing a particular dimension produces
the explicit empty-set semantics above. A UI action must distinguish these two
operations. Draft selections are separate from the applied context; old results
cannot be labelled as reflecting an uncompleted request.

## Authorization, options and errors

Authenticate and require approval/password policy exactly as the existing API.
For every request, validate the **complete** selected court set against current
session permissions before querying records or returning counts. A mixed
authorized/unauthorized selection returns 403 as a whole; never drop its denied
member or disclose counts. Recheck permissions when reading a snapshot or PDF.
The existing support-account policy applies; this contract adds no privilege.

Proposed options response returns `contract_version`, resolved `default_context`,
authorized courts, source identifiers/type/institution, availability/reason,
observed coverage and refresh, supported outcome categories, and approved subject
policy/version. Only expose court-specific availability within authorized scope.
Sources have explicit configuration identities; options' availability and counts
come from loaded data, not assumptions based on the presence of a connector.
Metadata-only, restricted, unavailable, pending-review and approved states differ.

Use 401 unauthenticated; 403 unauthorized scope; 400 invalid query; 503 unavailable
service/database. Successful data responses distinguish `empty` (valid scope, no
matching records), `partial` (incomplete selected source/period coverage), and
`unavailable` **per metric** (inapplicable unit or insufficient denominator).
Return machine-readable reasons and counts/exclusions; unknown evidence is never
coerced to denial or a real zero. All responses/PDFs retain coverage limitations.

## Combination and applicability

Use OR within each dimension and AND across dimensions applicable to the record
type. A cross-source join must use distinct record identity/EXISTS, not multiply
facts through subjects, theses, citations or duplicate links.

| Record type | Court | Period | Source | Outcome | Counting unit |
|---|---|---|---|---|---|
| DataJud metadata | Document's tribunal | Filing date | datajud | Display category only | One namespaced DataJud document |
| TJDFT/STJ decision text | Deciding court | Decision date; missing dates excluded/disclosed | Corresponding jurisprudence source | Only an evidenced reviewed decision outcome; absent result remains unknown | One official decision document/version |
| STJ authority | STJ institution, distinct from local deciding court | Authority validity under #118, not DataJud filing date | stj_precedent | Not applicable | One authority identity/version |
| BDJur doctrine | Not applicable; institution is BDJur, not a court | Publication date; missing dates excluded/disclosed | bdjur_doctrine | Not applicable | One bibliographic item/version |
| Adherence assessment | Local deciding court TJDFT | Local decision date plus reviewed authority temporal eligibility | Requires selected STJ precedent evidence | Display restriction on local outcome only when evidenced | One reviewed local decision–authority link |

Responses disclose `period_field`, `court_filter_applied`, `outcome_filter_applied`
and unit per section. The same date range can refer to different documented date
fields; those populations cannot be silently combined. Doctrine remains visible
for a doctrine-only selection even when courts are empty, because it has no
deciding court. Outcomes never remove doctrine/authority records.

TJDFT-only means its outcome-bearing document population only. Users can still
explicitly select STJ precedent context; the panel then labels `local_court=TJDFT`
and `reference_institution=STJ`, without adding STJ decisions to local rates.
STJ-only has no local TJDFT adherence population and returns that metric as
unavailable. Excluding `stj_precedent` excludes adherence comparisons rather than
silently consulting unselected authority. No source coverage is inferred from a
shared process number, similar text, or the existence of STJ process metadata.

## Population versus display filters

For DataJud cards, first select courts, source, subjects and filing dates. Compute
granted and denied counts and binary denominator from that complete population:

```text
binary_denominator = population.granted + population.denied
grant_rate = population.granted / binary_denominator
denial_rate = population.denied / binary_denominator
```

Return null rates for zero denominator or no applicable source. All other
categories are reported as exclusions. `outcomes` only selects displayed rows and
distribution series. Each series rate uses the population denominator; selected
series need not sum to 100%. Cards expose population counts separately from
displayed counts. An empty outcome selection has empty series with unchanged
population rates; an empty source selection has no applicable document population.

Do not add decision texts or doctrine to DataJud counts. If multiple selected
sources represent the same legal decision, expose separate typed populations and
reviewed links; do not claim a deduplicated appeal count without validated identity.
`analyzed_appeals` stays null until that grain has been reviewed and implemented.
Alignment's comparable denominator remains approved eligible aligned+divergent
links, separately excluding distinguishing, uncertain, pending/unapproved and
temporally ineligible evidence. #118 must review the temporal rules before use.

## Stable identity and reproducible export

`query_id = SHA256(UTF8(canonical JSON))`, where JSON has lexicographically sorted
keys, no whitespace, sorted unique arrays, no NaN/Infinity and explicit defaults.
Changing a selected category changes query_id even if the population rate does
not change. This is filter identity, not proof that the underlying data is frozen.

A server-generated snapshot contains canonical context, query_id, generation
timestamp, observed refresh/coverage, source/document/text revisions, authorized
scope fingerprint, subject-policy version, outcome rule, model/NLP versions and
quality/review state, metric numerator/denominator/exclusions, chart data and exact
selected supporting passages/links. `snapshot_id` identifies that immutable
materialized result. Dataset run IDs or max refresh time alone are insufficient
to reproduce mutable warehouse rows. #129 must materialize the complete snapshot
under a consistent database read and retain its provenance/expiry.

Dashboard sections and PDF receive the same snapshot_id. Export must not rerun
queries against changing current data and label them the old context. If the
snapshot is absent/expired return 409 `snapshot_unavailable` and require an
explicit refresh; never silently regenerate it. Enforce current authorization
and source rights before access. A hash or snapshot identifier is not a bearer
credential. Access revocation overrides a previously captured snapshot.

## Independently calculated examples

See [the synthetic oracle](fixtures/analytical-context-v1.json). It supplies four
TJDFT documents (granted, denied, partial, unknown), two STJ documents (granted,
denied), and one separate BDJur bibliographic item. All dates are January 2024;
one TJDFT document carries two subjects to exercise duplicate-join protection.
No approved legal comparison or NLP label is invented by these examples.

| Case | DataJud population | Binary base | Grant rate | Displayed binary bars | Doctrine |
|---|---:|---:|---:|---|---:|
| TJDFT alone | 4 | 2 | 1/2 | granted 1, denied 1 | 0 |
| TJDFT + STJ | 6 | 4 | 1/2 | granted 2, denied 2 | 0 |
| Combined, granted + partial selected | 6 | 4 | 1/2 | granted 2; partial is separately excluded | 0 |
| Doctrine only | 0 | 0 | null | none; outcome unit inapplicable | 1 |
| No matching dates | 0 | 0 | null | none | 0 |
| Requested BDJur unavailable | 6 | 4 | 1/2 | granted 2, denied 2; partial coverage | 0 |
| Unauthorized STJ in combined selection | No query | No disclosure | No disclosure | HTTP 403 for the whole request | No disclosure |

Expected values are literal hand counts in the oracle, not values generated by
the production implementation. #166/#167/#129 must reconcile their independent
outputs against them and add real-source cases. A reviewer must approve this
contract and its examples before those tasks claim their start prerequisites.

Run the independent offline review aid from the repository root:

```text
python backend/docs/verify_context_examples.py
```

It checks 12 literal cases, duplicate/order-invariant identity, whole-selection
authorization, preserved population denominators and doctrine separation. It
does not connect to Django, exercise an implemented v2 endpoint, or establish
legal/source approval. No production data or environment secrets are required.
