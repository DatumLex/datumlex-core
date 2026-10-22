# Sprint 2 baseline and traceability audit — 2026-10-21

Supporting contribution to #169, owned by ThiagoChaves13. No historical issue has
been reopened, reassigned or declared accepted by this audit.

## Reproduction boundary

- Audited remote main: `e62e1616862a834f47124103d50f7a002b9ca561` (PR #176 merged).
- Local checkout `D:/Api/datumlex-core`: `e86ee72`, with pre-existing staged and
  unstaged changes. Preserved without reset, stash, commit or migration.
- New isolated worktree: `D:/Api/datumlex-sprint2`, from remote main.
- Documentation baseline: October 14 academic-calendar update; Sprint 2 plan and
  client alignment include the October 7 refinement of September 22/25 feedback.
- Read all 45 Sprint 2 issue bodies, acceptance criteria and sequencing. Issue
  states/assignees come from the GitHub API snapshot. Project fields are separate:
  the live planning view shows four Backlog epics. Do not infer every child status
  from its epic, or treat a closed issue as independently verified Done.
- Priority and story estimates below refer to issue/planning text unless the live
  Project field is explicitly verified. Ten historical estimates total 100 SP;
  three newer stories are unestimated. These are not current capacity or velocity.
- Git identity matches Bima0195's verified primary GitHub email (checked in account
  settings). Existing commits and other contributors' changes retain authorship.

## Consolidated diagnosis before implementation

The baseline implements DataJud TJDFT/STJ metadata ingestion, an auditable STJ
text collector, manual reviewed-reference import, document-level outcome proxies,
session/court access control, and a React dashboard. It does not implement the
integrated Sprint 2 research-to-PDF journey. Source text, approved authority,
human-reviewed comparisons and legal doctrine remain different populations.

Three of 62 baseline Django tests failed: obsolete v2 rule-version expectation,
obsolete exclusion of STJ SUP documents, and a test selecting the STJ endpoint
through search scope although the current client selects court in its constructor.
The extraction command already supplies the court to that constructor. These are
stale test contracts, not evidence that the command calls the wrong endpoint.

The existing CI runs `npm install`/`npm test` at repository root, which has no
package manifest; frontend has no `test` script. Backend tests/static checks are
not run. Ruff additionally reports import-order violations, a duplicate dictionary
key and an unused migration-local variable. The collector uses Windows `msvcrt`
locking, so its complete existing suite must currently run on Windows.

## Historical baseline evidence

| Issue | Available evidence | Missing output and Sprint 2 impact |
|---|---|---|
| #5, #34, #35 | Current methodology and outcome tests; issue comments are generic completion or earlier requests for evidence | Reviewed scope/grain baseline and G1/G2 reconciliation are not established by closure. Affects #104/#165/#118. |
| #41 | Models/dictionary and generic completion comment | Independent review/version of all four artifacts is not linked in the inspected comment. Affects dependent model extensions. |
| #47 | September 23 comment: 22,757 retrieved, 22,746 loaded, 11 rejected; denominator 2,246, excluded 20,500, local PostgreSQL | Comment explicitly says Railway pending; later generic closure adds no deployment evidence. Historical counts are not a fresh runtime measurement. |
| #51 | Distribution narrows displayed series while card population remains unchanged; tests exercise denominator invariance | Current UI has no outcome control; Sprint 2 requires consistent multiselect across the journey. |
| #74 | Backend README is an endpoint reference; story still open | Complete response/schema/error examples and current environments need reconciliation. |
| #89 | Historical local validation document and generic completion comment | No same-release deployed source/API/UI/PDF evidence or PO acceptance established. Blocks #171 acceptance. |

## Analytical and hosting decisions

`fact_resource` is one DataJud source document, not one individual appeal. CNJ
process numbers can repeat across degrees/documents. Subject bridges do not
multiply counts. Binary rate is granted/(granted+denied); zero denominator is null.
TJDFT uses G2/TR, STJ uses SUP; partial, unknown, not-admitted and other excluded
categories remain separate. `analyzed_appeals` is null. Filing quarter volume
is not first-instance merit, a linked appeal, or reversal. Alignment counts approved
decision-to-precedent links with a comparable aligned+divergent denominator;
doctrine is supporting context and never an outcome or adherence denominator.

The September 22 record reports an academic hosting constraint. Documentation
still names Vercel/Railway, main contains Render Blueprint and local-server
packaging, and PR #159 is open. This audit does not select a provider or claim a
current deployment. PO/project representative must record the accepted academic
hosting choice; environment owner must supply access and same-release smoke
results. Do not change production or restore databases during baseline validation.

## Requirement → story → issue → files → tests/evidence → status

Classification is audit evidence, distinct from GitHub issue state and Project
status. No row below is labelled proven Done without its complete DoD evidence.

| Client requirement | Story/epic | Issue | Owner / issue state | Files | Tests / evidence / remaining input | Audit classification |
|---|---|---|---|---|---|---|
| Cross-source evidence | Epic/story | [#96 — Epic 8: Cross-Source Legal Data Foundation](https://github.com/DatumLex/datumlex-core/issues/96) | Unassigned / open | See child task rows | Integrated story/epic acceptance is not established by completed child code | Partially implemented |
| Cross-source evidence | #96 | [#97 — US-28 — Integrate STJ Jurisprudence and Precedents](https://github.com/DatumLex/datumlex-core/issues/97) | Unassigned / open | See child task rows | Integrated story/epic acceptance is not established by completed child code | Partially implemented |
| Cross-source evidence | #97 | [#98 — TASK — Validate STJ source access and retrieval scope](https://github.com/DatumLex/datumlex-core/issues/98) | JohnatanCoelho / closed | etl/STJ-ARCHITECTURE.md; backend/src/api/datajud_client.py | tests.test_stj; PR #173 and screenshot comment on #98; source/rights review still needed | Implemented, not independently validated |
| Cross-source evidence | #97 | [#99 — TASK — Implement auditable STJ jurisprudence ingestion](https://github.com/DatumLex/datumlex-core/issues/99) | ThiagoChaves13 / closed | etl/stj_documents.py; backend/src/etl/stj_ingestion.py; backend/src/db/models.py | tests.test_stj_documents; tests.test_stj_audit; PR #176 merged; backend/docs/evidence/task-99-stj-reconciliation.json; review #104 remains to verify | Implemented, not independently validated |
| Cross-source evidence | #96 | [#100 — US-29 — Integrate BDJur and Approved Open Doctrine](https://github.com/DatumLex/datumlex-core/issues/100) | Unassigned / open | See child task rows | Integrated story/epic acceptance is not established by completed child code | Partially implemented |
| Cross-source evidence | #100 | [#101 — TASK — Assess BDJur and open-doctrine source feasibility](https://github.com/DatumLex/datumlex-core/issues/101) | Unassigned / open | No source feasibility report found in main | Independent bounded research is available; rights cannot be inferred from public availability | Not started |
| Cross-source evidence | #100 | [#102 — TASK — Implement doctrine ingestion with rights and provenance](https://github.com/DatumLex/datumlex-core/issues/102) | ThiagoChaves13 / closed | backend/src/db/management/commands/import_alignment_corpus.py; backend/src/db/models.py | Importer supports doctrine references; no BDJur harvesting connector, author/rights/version model or real doctrine reconciliation found in main; no linked PR evidence in issue | Partially implemented |
| Cross-source evidence | #96 | [#103 — US-30 — Normalize and Link Cross-Source Legal Records](https://github.com/DatumLex/datumlex-core/issues/103) | Unassigned / open | See child task rows | Integrated story/epic acceptance is not established by completed child code | Partially implemented |
| Cross-source evidence | #103 | [#104 — TASK — Extend the model for cross-source provenance](https://github.com/DatumLex/datumlex-core/issues/104) | Unassigned / open | backend/src/db/models.py; backend/docs/data-dictionary.md; etl/STJ-ARCHITECTURE.md | STJ versions and legal-reference tables exist; unified TJDFT/NLP/rights schema and reviewed four-artifact baseline remain | Partially implemented |
| Cross-source evidence | #103 | [#105 — TASK — Implement traceable cross-source matching](https://github.com/DatumLex/datumlex-core/issues/105) | Unassigned / open | backend/src/db/management/commands/import_alignment_corpus.py | Reviewed manual links can be imported; automated/candidate linkage and real precision assessment absent | Partially implemented |
| Explainable NLP | Epic/story | [#106 — Epic 9: NLP Thesis and Legal Reasoning Extraction](https://github.com/DatumLex/datumlex-core/issues/106) | Unassigned / open | See child task rows | Integrated story/epic acceptance is not established by completed child code | Blocked |
| Explainable NLP | #106 | [#107 — US-31 — Extract Legal Grounds and Thesis Candidates](https://github.com/DatumLex/datumlex-core/issues/107) | Unassigned / open | See child task rows | Integrated story/epic acceptance is not established by completed child code | Blocked |
| Explainable NLP | #107 | [#108 — TASK — Define the legal NLP taxonomy and annotation guide](https://github.com/DatumLex/datumlex-core/issues/108) | Unassigned / open | No approved annotation guide found in main | Traceable real examples and legal/PO review required; drafting can proceed | Blocked |
| Explainable NLP | #107 | [#109 — TASK — Implement the thesis and grounds extraction pipeline](https://github.com/DatumLex/datumlex-core/issues/109) | Unassigned / open | Not found in audited main | Required reviewed source/schema/taxonomy/context/method inputs listed in issue are not yet established | Blocked |
| Explainable NLP | #106 | [#110 — US-32 — Validate NLP Quality with Human Review](https://github.com/DatumLex/datumlex-core/issues/110) | Unassigned / open | See child task rows | Integrated story/epic acceptance is not established by completed child code | Blocked |
| Explainable NLP | #110 | [#111 — TASK — Build a representative legal NLP benchmark](https://github.com/DatumLex/datumlex-core/issues/111) | Unassigned / open | Not found in audited main | Required reviewed source/schema/taxonomy/context/method inputs listed in issue are not yet established | Blocked |
| Explainable NLP | #110 | [#112 — TASK — Evaluate NLP quality and approve release thresholds](https://github.com/DatumLex/datumlex-core/issues/112) | Unassigned / open | Not found in audited main | Required reviewed source/schema/taxonomy/context/method inputs listed in issue are not yet established | Blocked |
| Explainable NLP | #106 | [#113 — US-33 — Expose Explainable NLP Results](https://github.com/DatumLex/datumlex-core/issues/113) | Unassigned / open | See child task rows | Integrated story/epic acceptance is not established by completed child code | Blocked |
| Explainable NLP | #113 | [#114 — TASK — Persist versioned NLP evidence and corrections](https://github.com/DatumLex/datumlex-core/issues/114) | Unassigned / open | Not found in audited main | Required reviewed source/schema/taxonomy/context/method inputs listed in issue are not yet established | Blocked |
| Explainable NLP | #113 | [#115 — TASK — Add explainable thesis endpoints and interface states](https://github.com/DatumLex/datumlex-core/issues/115) | Unassigned / open | Not found in audited main | Required reviewed source/schema/taxonomy/context/method inputs listed in issue are not yet established | Blocked |
| Precedent adherence | Epic/story | [#116 — Epic 10: Comparative Legal Intelligence](https://github.com/DatumLex/datumlex-core/issues/116) | Unassigned / open | See child task rows | Integrated story/epic acceptance is not established by completed child code | Partially implemented |
| Precedent adherence | #116 | [#117 — US-34 — Measure Adherence to Superior-Court Precedents](https://github.com/DatumLex/datumlex-core/issues/117) | Unassigned / open | See child task rows | Integrated story/epic acceptance is not established by completed child code | Partially implemented |
| Precedent adherence | #117 | [#118 — TASK — Define precedent-adherence methodology](https://github.com/DatumLex/datumlex-core/issues/118) | Unassigned / open | backend/docs/precedent-alignment.md | Existing link-based formula; temporal authority eligibility, real reviewed examples and legal approval remain | Partially implemented |
| Precedent adherence | #117 | [#119 — TASK — Implement adherence metrics and evidence drill-down](https://github.com/DatumLex/datumlex-core/issues/119) | Unassigned / open | backend/src/routes/statistics.py; frontend/src/App.jsx | /api/alignment/ exists; canonical context, temporal eligibility and evaluated NLP evidence absent; no dedicated alignment test module in main | Partially implemented |
| Divergence (Should Have) | #116 | [#120 — US-35 — Identify Divergent Understandings](https://github.com/DatumLex/datumlex-core/issues/120) | Unassigned / open | See child task rows | Integrated story/epic acceptance is not established by completed child code | Blocked |
| Divergence (Should Have) | #120 | [#121 — TASK — Define divergence detection and safeguards](https://github.com/DatumLex/datumlex-core/issues/121) | Unassigned / open | Not found in audited main | Required reviewed source/schema/taxonomy/context/method inputs listed in issue are not yet established | Blocked |
| Divergence (Should Have) | #120 | [#122 — TASK — Implement chamber and panel comparison views](https://github.com/DatumLex/datumlex-core/issues/122) | Unassigned / open | Not found in audited main | Required reviewed source/schema/taxonomy/context/method inputs listed in issue are not yet established | Blocked |
| Temporal exploration (Could Have) | #116 | [#123 — US-36 — Explore Temporal Trends and Main Theses](https://github.com/DatumLex/datumlex-core/issues/123) | Unassigned / open | See child task rows | Integrated story/epic acceptance is not established by completed child code | Partially implemented |
| Temporal exploration (Could Have) | #123 | [#124 — TASK — Implement version-aware temporal aggregates](https://github.com/DatumLex/datumlex-core/issues/124) | Unassigned / open | backend/src/routes/statistics.py | Quarterly reviewed-link series exists; version/coverage boundaries and shared context absent | Partially implemented |
| Temporal exploration (Could Have) | #123 | [#125 — TASK — Build the temporal and thesis exploration experience](https://github.com/DatumLex/datumlex-core/issues/125) | Unassigned / open | frontend/src/App.jsx | Existing alignment trend UI; full version-aware exploration and canonical context absent | Partially implemented |
| Reproducible PDF | #160 | [#127 — US-37 — Export a Reproducible PDF Report](https://github.com/DatumLex/datumlex-core/issues/127) | Unassigned / open | See child task rows | Integrated story/epic acceptance is not established by completed child code | Blocked |
| Reproducible PDF | #127 | [#128 — TASK — Design the professional PDF report template](https://github.com/DatumLex/datumlex-core/issues/128) | Unassigned / open | No PDF template/export dependency found in package manifests | Template design can start with proposed context and brand; approval and rendering remain | Blocked |
| Reproducible PDF | #127 | [#129 — TASK — Implement and validate server-side PDF export](https://github.com/DatumLex/datumlex-core/issues/129) | Unassigned / open | Not found in audited main | Required reviewed source/schema/taxonomy/context/method inputs listed in issue are not yet established | Blocked |
| Research and delivery | Epic/story | [#160 — Epic 13: Dynamic Research, PDF Reports, and Sprint 2 Delivery](https://github.com/DatumLex/datumlex-core/issues/160) | Unassigned / open | See child task rows | Integrated story/epic acceptance is not established by completed child code | Blocked |
| TJDFT decision text | #96 | [#161 — US-43 — Retrieve Traceable TJDFT Decision Text](https://github.com/DatumLex/datumlex-core/issues/161) | Unassigned / open | See child task rows | Integrated story/epic acceptance is not established by completed child code | Partially implemented |
| TJDFT decision text | #161 | [#162 — TASK — Validate TJDFT decision-text access and coverage](https://github.com/DatumLex/datumlex-core/issues/162) | ThiagoChaves13 / open | Issue #162 report attachment | Comment reports 8 DataJud processes, 14 decisions and 11 retrieved texts; report posted by task owner; independently reviewed storage/link contract still required | Implemented, not independently validated |
| TJDFT decision text | #161 | [#163 — TASK — Ingest and reconcile TJDFT decision text](https://github.com/DatumLex/datumlex-core/issues/163) | Unassigned / open | Not found in audited main | Required reviewed source/schema/taxonomy/context/method inputs listed in issue are not yet established | Blocked |
| Dynamic multiselect | #160 | [#164 — US-44 — Explore a Shared Dashboard with Dynamic Multiselect Filters](https://github.com/DatumLex/datumlex-core/issues/164) | Unassigned / open | See child task rows | Integrated story/epic acceptance is not established by completed child code | Partially implemented |
| Dynamic multiselect | #164 | [#165 — TASK — Define multiselect filters and analytical-context semantics](https://github.com/DatumLex/datumlex-core/issues/165) | Unassigned / open | Current single-value API contract in backend/src/services/statistics_service.py | Research/design can start independently; proposed contract is the next deliverable | Not started |
| Dynamic multiselect | #164 | [#166 — TASK — Implement multiselect API queries and source options](https://github.com/DatumLex/datumlex-core/issues/166) | Unassigned / open | backend/src/services/statistics_service.py; backend/src/accounts/middleware.py | Current parser rejects repeated values and middleware authorizes one court only; reviewed #165/#104 required | Not started |
| Dynamic multiselect | #164 | [#167 — TASK — Build and validate dynamic multiselect dashboard controls](https://github.com/DatumLex/datumlex-core/issues/167) | Unassigned / open | frontend/src/App.jsx; frontend/src/api.js | Current overview uses one court; combined label in precedents tab is not multiselect | Not started |
| Integrated release | #160 | [#168 — US-45 — Validate and Publish the Sprint 2 Increment](https://github.com/DatumLex/datumlex-core/issues/168) | Unassigned / open | See child task rows | Integrated story/epic acceptance is not established by completed child code | Partially implemented |
| Baseline audit | #168 | [#169 — TASK — Audit Sprint 1 baseline and Sprint 2 delivery blockers](https://github.com/DatumLex/datumlex-core/issues/169) | ThiagoChaves13 / open | backend/docs/sprint-2-baseline-audit.md (this report) | Baseline reproduced in isolated worktree; owner remains ThiagoChaves13; supporting contribution only | Partially implemented |
| Integrated reconciliation | #168 | [#170 — TASK — Reconcile and test the Sprint 2 end-to-end increment](https://github.com/DatumLex/datumlex-core/issues/170) | Unassigned / open | Not found in audited main | Required reviewed source/schema/taxonomy/context/method inputs listed in issue are not yet established | Blocked |
| Deployment | #168 | [#171 — TASK — Deploy Sprint 2 and publish release and demo evidence](https://github.com/DatumLex/datumlex-core/issues/171) | Unassigned / open | Not found in audited main | Required reviewed source/schema/taxonomy/context/method inputs listed in issue are not yet established | Blocked |

## Execution sequence and review dependencies

1. Repair runnable baseline checks and publish this evidence without taking over
   #169's ownership. Request independent technical review before merge.
2. Draft #165's canonical context and independently calculated examples; preserve
   card-denominator invariance and authorization for the complete selected court set.
   This contract needs independent review before #166/#167/#129 implementation.
3. #101 bounded BDJur research can proceed independently. #162 has an owner and
   a posted report; ask for/review its source/sample artifacts without moving the
   owner's card. Neither public access nor report publication grants text reuse.
4. Incremental #104 contracts require reviewed source samples. #108/#111/#118
   require real passages and legal/PO decisions. Do not invent annotation labels,
   quality thresholds, binding authority or review approval to bypass dependencies.
5. Once inputs are reviewed, implement one dependent task at a time. #170/#171
   require actual integrated data, NLP quality, shared filters, PDF and deployment.

## Validation of the baseline repair

- Isolated SQLite: 63 Django tests passed after correcting stale contracts and
  adding supported/admission-only STJ movement regression cases.
- Django system check: passed. Migration drift: no changes detected.
- Ruff with the explicit backend configuration: passed after import cleanup,
  removal of a shadowed dictionary entry and an unused migration-local variable.
- Workflow changes were removed from PR #178 at the project representative's
  request to avoid conflicts. The existing main workflow is preserved. Local
  backend/frontend validation and its evidence remain part of this delivery.
- Frontend ESLint and production build passed. The dependency audit initially
  reported three high-severity packages; compatible lockfile updates corrected
  them and the repeated npm audit reported zero vulnerabilities. The previously
  passing hosted run used the earlier workflow revision; it is historical evidence
  and does not describe the current PR workflow after its removal from scope.
- Tests use controlled fixtures; no development/production data was migrated,
  recollected, modified or claimed as a fresh real-source validation.
- Independent review, hosting decision and integrated release acceptance remain
  outstanding. This contribution does not close #169 or its parent story.

## Live Project verification and execution handoff

All 45 Sprint 2 issue Project sidebars were subsequently inspected through the
authenticated GitHub UI. [Captured visible fields](evidence/sprint-2-project-fields-2026-10-21.json)
include Status, Priority, Sprint, Estimate and Start/End; none was inferred from
its epic. This is a later execution snapshot, after #101/#165 entered review.
The API token lacks project scope; no credential permissions were expanded.

Observed status totals: {'Backlog': 38, 'In progress': 1, 'Done': 3, 'In review': 2, 'Ready': 1}. Existing story estimates sum to 100 SP;
three new stories remain unestimated. All 45 items have no Start/End dates.
Dates, priorities and estimates were not changed by this work.

| Issue | Project status | Priority | Estimate | Sprint |
|---|---|---|---|---|
| #96 | Backlog | Must Have | — | Sprint 2 |
| #97 | In progress | Must Have | 8 | Sprint 2 |
| #98 | Done | Must Have | — | Sprint 2 |
| #99 | Done | Must Have | — | Sprint 2 |
| #100 | Backlog | Must Have | 8 | Sprint 2 |
| #101 | In review | Must Have | — | Sprint 2 |
| #102 | Done | Must Have | — | Sprint 2 |
| #103 | Backlog | Must Have | 13 | Sprint 2 |
| #104 | Backlog | Must Have | — | Sprint 2 |
| #105 | Backlog | Must Have | — | Sprint 2 |
| #106 | Backlog | Must Have | — | Sprint 2 |
| #107 | Backlog | Must Have | 13 | Sprint 2 |
| #108 | Backlog | Must Have | — | Sprint 2 |
| #109 | Backlog | Must Have | — | Sprint 2 |
| #110 | Backlog | Must Have | 13 | Sprint 2 |
| #111 | Backlog | Must Have | — | Sprint 2 |
| #112 | Backlog | Must Have | — | Sprint 2 |
| #113 | Backlog | Must Have | 8 | Sprint 2 |
| #114 | Backlog | Must Have | — | Sprint 2 |
| #115 | Backlog | Must Have | — | Sprint 2 |
| #116 | Backlog | Must Have | — | Sprint 2 |
| #117 | Backlog | Must Have | 13 | Sprint 2 |
| #118 | Backlog | Must Have | — | Sprint 2 |
| #119 | Backlog | Must Have | — | Sprint 2 |
| #120 | Backlog | Should Have | 8 | Sprint 2 |
| #121 | Backlog | Should Have | — | Sprint 2 |
| #122 | Backlog | Should Have | — | Sprint 2 |
| #123 | Backlog | Could Have | 8 | Sprint 2 |
| #124 | Backlog | Could Have | — | Sprint 2 |
| #125 | Backlog | Could Have | — | Sprint 2 |
| #127 | Backlog | Must Have | 8 | Sprint 2 |
| #128 | Backlog | Must Have | — | Sprint 2 |
| #129 | Backlog | Must Have | — | Sprint 2 |
| #160 | Backlog | Must Have | — | Sprint 2 |
| #161 | Backlog | Must Have | — | Sprint 2 |
| #162 | Ready | Must Have | — | Sprint 2 |
| #163 | Backlog | Must Have | — | Sprint 2 |
| #164 | Backlog | Must Have | — | Sprint 2 |
| #165 | In review | Must Have | — | Sprint 2 |
| #166 | Backlog | Must Have | — | Sprint 2 |
| #167 | Backlog | Must Have | — | Sprint 2 |
| #168 | Backlog | Must Have | — | Sprint 2 |
| #169 | Backlog | Must Have | — | Sprint 2 |
| #170 | Backlog | Must Have | — | Sprint 2 |
| #171 | Backlog | Must Have | — | Sprint 2 |

### Concrete deliveries

| Task | Branch / commit | PR | Validation and completion boundary |
|---|---|---|---|
| #177, supporting #169 | fix/177-sprint2-baseline-validation / 8389dad | [#178](https://github.com/DatumLex/datumlex-core/pull/178) | 63 isolated Django tests, no migration drift, Ruff, frontend lint/build/audit passed. Workflow changes later removed at the project representative's request; prior hosted success is historical. Independent review pending. |
| #165 | documentation/165-analytical-context / 75e9a79 | [#179](https://github.com/DatumLex/datumlex-core/pull/179) | Canonical contract and 12 hand-counted cases checked offline; no active API change. Independent API/model/UI/PDF review required before dependent implementation. |
| #101 | documentation/101-bdjur-source-feasibility / 6949789 | [#180](https://github.com/DatumLex/datumlex-core/pull/180) | Six official-route probes returned 403; report separates indexed candidates from live access and rights. Source/PO review required; no approved BDJur corpus. |

All commits use Bima0195's existing verified identity, without assistant
coauthorship. #101/#165/#177 are In review; none was marked Done. #169 remains
owned by ThiagoChaves13 with its original status. Main has not been merged or
modified, and the original local staged/unstaged changes remain intact.

All three PRs now retain main's existing workflow; changes to CI are outside
this delivery at the project representative's request. Local validation results
remain valid. The earlier hosted backend/frontend success applies only to the
earlier workflow revision. No current hosted CI success, authenticated real-data
dashboard/PDF run or deployment acceptance is claimed.

Remaining implementation requires the explicit reviewed inputs recorded in the
matrix: source access/rights (#101/#162), model/link contracts (#104), annotation
and legal-method guidance (#108/#118), independently reviewed NLP benchmark and
release thresholds (#111/#112), and canonical context (#165). Do not bypass these
inputs by inventing approval, thresholds, text coverage or production behavior.
