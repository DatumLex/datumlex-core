# Deterministic code / name / complement mapping

Run from `backend`:

```powershell
.venv/Scripts/python.exe manage.py map_records --input tests/fixtures/mapping/records.json --rules tests/fixtures/mapping/rules.json --output data/mapping-example-report.json
.venv/Scripts/python.exe manage.py test tests.test_deterministic_mapping -v 2
```

The output must be a new file in an existing directory. Existing files are never overwritten.
The example is synthetic and does not establish approval of judicial classifications.

Rules require a unique `id`, a target, a nonempty `rule_version`, exact field values
under `match`, and evidence containing a source or file (optionally a positive line).
Each field under `match` independently associates its exact value with a target;
these are field mappings, not conditional conjunctions. Do not use this format for
a complement whose meaning depends on a particular code. Such contextual rules
require a separately reviewed rule design.

Values use exact JSON equality: no case folding, fuzzy matching, type coercion,
NLP, GenAI, or inference from unregistered text. Object key order is ignored;
array order remains significant. An unknown field never supplies a target.

| Status | Meaning |
| --- | --- |
| complete | All three fields match and identify one common target |
| partial | One common target, but at least one field is absent or unmapped |
| unknown | No field matches |
| conflict | Recognized fields have no common target, or multiple common targets |

`partial` describes mapping completeness, not the legal outcome of partial allowance.
Conflicts never choose the first rule or emit a target. The four fixture records
expect complete/partial/unknown/conflict, respectively. Their targets are
synthetic_allowed/synthetic_allowed/null/null.

Each report persists the input, status, target, candidate targets, unmatched fields,
rule version, SHA-256 of the rule snapshot, exact matching values, rule IDs, source
references, and input file plus JSON pointer. The full rules snapshot is included,
so later changes to the rules file do not change the evidence in earlier reports.
Source references are supplied by the rule author; the software validates their
presence, not their truth or review status. Reports include input values and should
be stored with the same access restrictions as their source data.

This command is an independent auditable mapping workflow. It does not migrate or
reclassify existing warehouse records or change dashboard rates. The existing
TPU outcome classifier remains unchanged. Before using this mapper for task #45's
judicial classifications, supply and review the actual code/name/complement
mapping and agree on how to integrate its conflict statuses into the warehouse.
