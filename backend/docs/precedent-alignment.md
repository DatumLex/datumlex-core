# Precedent and doctrine alignment

The panel at `/api/alignment/` compares TJDFT decisions with explicit STJ
precedent and BDJur doctrine references. It never infers legal adherence from
DataJud movement codes, textual similarity, shared process numbers, or the
existence of an STJ process. DataJud remains the source for process metadata;
the legal reference corpus and each decision-to-reference assessment carry
their own citation and approval lineage.

## Cross-source citation reconciliation

`sync_pangea` imports STJ precedent records and explicitly listed representative
processes from Pangea's public search API. It reads the public catalog first,
restricts the query to STJ, and saves the query, catalog version, page coverage,
source update date, and a payload hash for audit. The scheduled source job then runs
`match_stj_citations`, which compares a citation only when it contains the
complete 20-digit CNJ identifier with a local TJDFT process number. The
normalization removes punctuation; it does not infer CNJ digits from a short
REsp/AREsp citation, title, subject, or textual similarity. Re-running the
command is idempotent. Links retain both database endpoints, the cited source
identifier and locator, rule version, confidence, and review status.

An exact identifier match has confidence `1.0000` for **process identity only**;
it does not measure legal similarity, adherence, or precedent applicability.
Unmatched and non-CNJ citations are stored as unresolved with no confidence and
remain separate from matched candidates. Reconciliation candidates do not
create `DecisionAssessment` rows or affect adherence/divergence totals. The API
does not apply the selected decision-date filter to these candidates because
the current DataJud process facts do not provide a verified judgment date.

### Initial evidence and limits

The locally available, sourced STJ edition-125 sample contains citations such
as `REsp 1771866/DF`, while DataJud stores CNJ process identifiers. Without
retrieved decision text or an official mapping between those formats, these
citations cannot be joined safely. The exact-CNJ rule therefore deliberately
leaves them unresolved. The available local DataJud set has TJDFT process
metadata but no TJDFT decision text; task #163 is still a prerequisite for
full citation extraction. The integrated public Pangea search does not require
OAuth credentials. The separate legacy client for authenticated BNP resources
still supports client credentials. The official [PDPJ-Br Pangea integration
guide](https://docs.pdpj.jus.br/servicos-negociais/pangeabnp/) documents the
service and its authenticated resources.

The reproducible matcher fixtures cover complete-ID matches, non-CNJ
citations, malformed identifiers, duplicate citations and idempotent reruns.
They do not estimate real-corpus precision/recall or resolve false negatives
caused by missing full text. No fuzzy-match threshold is enabled. A reviewed
real-source sample and the decision-text ingestion task are still required
before widening matching beyond exact identifiers.

The Pangea public catalog and STJ search endpoint were verified during integration.
For the query `responsabilidade civil`, a live search returned 220 results and
all were imported in three pages. Scheduled collection now also queries
consumer, health, social-security, administrative, tax, and civil-procedure
themes. Each topic is capped at five pages of 100 per run, and each result
preserves which search terms returned it. One verified collection returned
2,414 search hits consolidated into 815 unique STJ references. The totals can change as the source is
updated. Public search does not require the
PDPJ-Br OAuth credentials used by other BNP resources. Pangea's
`ultimaAtualizacao` is only the source record's update date; it is not mapped to
judgment or publication date. Paradigm-process citations are source evidence for
identity matching only, not proof of precedent applicability or adherence. The
official [PDPJ-Br Pangea integration guide](https://docs.pdpj.jus.br/servicos-negociais/pangeabnp/)
describes the Pangea service and its authenticated resources.

## Review and indicator rules

Only records with `LegalReference.approved=true` and
`DecisionAssessment.review_state=approved` enter the indicators. A validated
assessment requires a reviewer, written rationale, and approval reference.
Evidence excerpts and source locators should point to the relevant passage in
the local decision and cited source.

- **Aderência** = validated links marked `aligned` divided by validated
  `aligned` plus `divergent` links.
- **Possíveis divergências** = validated links marked `divergent`; the rate
  uses the same comparable denominator. This is a review signal, not a legal
  conclusion.
- **Distinguishing** and **inconclusive** are displayed separately and excluded
  from both rates.
- The unit is a decision-to-reference link. One local decision can have several
  links. No linked record does not mean no applicable precedent exists.
- Trends use the locally recorded decision date, grouped by quarter. The date
  filter in this panel is separate from the DataJud dashboard's filing-date
  filter, even though the date controls share a range.

## Importing an approved corpus

The repository contains the import path and an initial, unapproved STJ source set; it does not contain an approved BDJur/STJ analytical corpus.
Obtain the reviewed source file through the project's approved BDJur process;
do not treat DataJud's case metadata as a substitute for an STJ thesis or a
doctrinal work. Each reference needs its institution (`STJ` for precedent,
`BDJur` for doctrine), a stable identifier, source URL and locator, and
approval reference. Only STJ precedents may receive an adherence assessment;
BDJur doctrine is preserved as approved supporting material and is not scored.
Each assessment links to a TJDFT DataJud
`source_id` (new imports use `TJDFT:<source-id>`; earlier local records may
retain their original unprefixed ID), a decision date, a reviewer,
a relation, a rationale, and its approval/evidence locator.

JSON format:

```json
{
  "references": [
    {
      "reference_type": "precedent",
      "source_institution": "STJ",
      "identifier": "REsp 0000000/DF",
      "title": "Título/identificação do precedente",
      "thesis": "Tese validada conforme a fonte oficial",
      "authority": "repetitivo",
      "subject_code": 10431,
      "source_name": "STJ — Repetitivos e IACs Anotados",
      "source_url": "https://processo.stj.jus.br/repetitivos/temas_repetitivos/?pesquisaAvancada=true",
      "source_locator": "Tema, seção ou página",
      "published_at": "2026-01-15",
      "approval_reference": "BDJur: referência de aprovação",
      "approved": true,
      "assessments": [
        {
          "local_source_id": "TJDFT:identificador-no-datajud",
          "decision_date": "2026-02-10",
          "relation": "aligned",
          "review_state": "approved",
          "rationale": "Fundamentação da classificação revisada",
          "evidence_excerpt": "Trecho curto da decisão local",
          "evidence_locator": "p. 4, item 2",
          "reviewer": "Identificação do revisor",
          "approval_reference": "Referência de validação"
        }
      ]
    }
  ]
}
```

Use `reference_type: doctrine` and `source_institution: BDJur` for BDJur
doctrinal materials; omit `assessments` for them. Supported
relations are `aligned`, `divergent`, `distinguished`, and `uncertain`;
supported review states are `pending`, `reviewed`, and `approved`. Import is
atomic: a missing local DataJud record or invalid mapping stops the entire
file.

After obtaining authorization and preparing the file, apply migrations and
import it from `backend`:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py import_alignment_corpus --input data\approved_alignment.json
```

The panel reports the loaded corpus and exposes citations, coverage and
limitations alongside the indicators. The official STJ data portal describes
the distinction between process metadata, curated jurisprudence, and qualified
precedent datasets. Public-source starting points include the [STJ Open Data
Portal](https://dadosabertos.web.stj.jus.br/) and [BDJur](https://bdjur.stj.jus.br/).

## Initial STJ source set

After applying migrations, load two traceable entries from the STJ's
*Jurisprudência em Teses*, edition 125, with:

```powershell
.venv/Scripts/python.exe manage.py load_stj_responsabilidade_civil
```

The idempotent command stores the edition's summaries on moral-damage
valuation (bifasic method) and collective moral damage, with STJ decisions
cited under each thesis. These records are visible as sourced material but
remain `approved=False`, so they do not affect adherence/divergence indicators
until the project's corpus approval process approves them. The edition's
research covers cases published through 26 April 2019 and states it is not an
official case-law repository. Its citations show what the edition cites; they
do not establish that a cited case is binding or that any TJDFT decision
follows it.
