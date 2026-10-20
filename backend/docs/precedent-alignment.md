# Precedent and doctrine alignment

The panel at `/api/alignment/` compares TJDFT decisions with explicit STJ
precedent and BDJur doctrine references. It never infers legal adherence from
DataJud movement codes, textual similarity, shared process numbers, or the
existence of an STJ process. DataJud remains the source for process metadata;
the legal reference corpus and each decision-to-reference assessment carry
their own citation and approval lineage.

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

The repository contains the import path, not an approved BDJur/STJ corpus.
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
