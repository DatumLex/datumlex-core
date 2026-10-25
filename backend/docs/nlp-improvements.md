# NLP and source-linked legal reports

## Current changes

- Rules version 0.2.0 recognizes additional numbered citation forms, including `Súmula n.º 7, do STJ`, `REsp n. 1.234.567/DF` and article subsections.
- Candidate retrieval requires the topic and the trigger in the same sentence, reducing unrelated paragraph-level matches. Original text, offsets and negation are preserved. Attribution and judicial adoption remain unknown pending review.
- Cache identity includes the actual extractor rule version. Existing archived evidence and human revisions are not rewritten.
- `src.nlp.evaluation.evaluate_annotations` reports exact-span/label precision, recall, F1 and error counts. Empty denominators remain unavailable. Duplicate identical predictions do not inflate scores.

These are engineering improvements verified with synthetic regression fixtures. They do not establish semantic accuracy or production legal quality. A representative, independently reviewed corpus and adjudicated annotations are still required before setting quality thresholds or selecting a semantic model. No external model service or paid provider was added.

## Reports and UI

The PDF leads with the research scope, a plain-language result summary, source-linked precedent excerpts and process metadata for locating the records. Detailed exclusions remain in reading notes. It does not invent case holdings or assess applicability.

The related-decisions panel separately displays original Pangea citations, even when no local assessment or identifier match exists. These citations are not legal alignment evidence. Unknown dates do not receive an implied temporal match. Only official source links are rendered.
