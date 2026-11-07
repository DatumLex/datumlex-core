# NLP and source-linked legal reports

## Multi-source processing

Pipeline 0.5.0 and rules 0.3.0 share the ten lexical civil liability topics
with the subject catalog. Text matches remain candidates with pending review.

The ETL process worker accepts jurisprudence, Pangea, and doctrine sources.
Pangea inputs use the original archived thesis or legal-question field, its
record identifier, court, response hash, and text hash. Doctrine inputs require
an extracted text with a matching hash and the matching archived PDF.
Bibliography-only entries are reported as excluded from NLP.

Each NLP result records the source category and topic matches. Pangea
references retain their court, while shared doctrine has an empty court and
retains its publisher. Authenticated, approved users can consult shared doctrine
evidence under the same access scope as the doctrine catalog. Review actions
continue to require a reviewer role.

Reference evidence is linked to the existing catalog entry using the source
payload hash. The catalog exposes the matching extraction identifier and NLP
status. Reprocessing preserves extraction history and leaves review pending.
The court coverage report counts jurisprudence separately from reference texts.

Run `scripts/run-etl.ps1 -Mode process -Sources 'doctrine,pangea' -Once`
to process archived reference material. The default source selection also
includes the jurisprudence queues. Pangea references with unknown dates are
reported as undated, with their source field preserved.

## Current changes

- Rules version 0.2.0 recognizes additional numbered citation forms, including `Súmula n.º 7, do STJ`, `REsp n. 1.234.567/DF` and article subsections.
- Candidate retrieval requires the topic and the trigger in the same sentence, reducing unrelated paragraph-level matches. Original text, offsets and negation are preserved. Attribution and judicial adoption remain unknown pending review.
- Cache identity includes the actual extractor rule version. Existing archived evidence and human revisions are not rewritten.
- `src.nlp.evaluation.evaluate_annotations` reports exact-span/label precision, recall, F1 and error counts. Empty denominators remain unavailable. Duplicate identical predictions do not inflate scores.

These are engineering improvements verified with synthetic regression fixtures. They do not establish semantic accuracy or production legal quality. A representative, independently reviewed corpus and adjudicated annotations are still required before setting quality thresholds or selecting a semantic model. No external model service or paid provider was added.

## Reports and UI

The PDF leads with the research scope, a plain-language result summary, source-linked precedent excerpts and process metadata for locating the records. Detailed exclusions remain in reading notes. It does not invent case holdings or assess applicability.

The related-decisions panel separately displays original Pangea citations, even when no local assessment or identifier match exists. These citations are not legal alignment evidence. Unknown dates do not receive an implied temporal match. Only official source links are rendered.
