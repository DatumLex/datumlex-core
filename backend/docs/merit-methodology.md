# Current rule: tpu-document-latest-v3

The dashboard calculates an exploratory result proxy per DataJud document. It does not count individual appeals and is not the tribunal-wide success rate. The date filter uses filing date, not judgment date. Data is a partial local extract.

The selected result is the mapped TPU movement with the latest `occurred_at` for each document. Undated movements cannot be selected. In a timestamp tie, the highest local movement ID wins; that is a technical tie-breaker, not legal precedence. Later movements outside the result mapping do not change the selected classification.

## Tribunal coverage and mapping

- **TJDFT:** degrees G2/TR; codes 237 and 972 (granted), 239 (denied), 238 (partial), 235 (not admitted), and 240–242 (partial knowledge/result combinations).
- **STJ:** degree SUP; the shared codes above plus STJ TPU events 12434 (grant of the Recurso Especial), 12435 (denial), 12436 (not known), 12438 (partial grant), and 12439/12440/12443 (partial-knowledge combinations). Admission/conversion-only events 12437, 12441 and 12442 do not establish a merits result and are not mapped.

Only fully granted and fully denied documents enter the binary denominator. Partial, partial-knowledge, not-admitted, unknown and other-degree documents are listed as exclusions. This is conservative: a movement can describe one appeal or party among several in a DataJud process record, so the figures are document-level proxies and cannot be read as results for each appeal. The STJ-specific definitions are in the [CNJ SGT movement table](https://www.cnj.jus.br/sgt/gerenciar_complementos.php); CNJ describes the TPU as a standardized movement taxonomy, not as a curated precedent or doctrine database.

The migration `0004_stj_merit_outcomes` reclassifies the already-loaded STJ snapshot so the dashboard does not require re-downloading all documents. Future imports apply the same current rule in the loader. `/api/processes/` returns selected evidence and the rule version.

## Formula

Binary denominator = granted documents + denied documents. Grant rate = granted / denominator; denial rate = denied / denominator. If the denominator is zero, both rates are `null`. Subject filters do not multiply documents. The indicator does not count individual appeals; `analyzed_appeals` remains `null`.
