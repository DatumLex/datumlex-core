# Current rule: tpu-document-latest-v2

The selected outcome is the mapped procedural event with the latest occurred_at for each document. In a tie, the highest local process_movement ID wins (the requested technical tiebreaker, not legal precedence). Undated events are not eligible for selection; without a dated outcome, the document is classified as unknown. Later events unrelated to an outcome do not change the classification. A mixed history no longer excludes documents. If the selected outcome is partially allowed or not admitted for review, it remains outside the binary denominator. selected_evidence exposes the code, date, and ID used. IDs are local and may change when events are reloaded.

The per-document denominator, filters, and limitations remain unchanged. The previous rule below is retained only for historical reference and has been superseded.

# Per-document rates — tpu-document-v1

This is an exploratory indicator calculated from DataJud documents in G2/TR, not a count of individual appeals. The unit of the dimensional model remains source_id. The query uses the filing date, not the judgment date. The local extract is partial and cannot be used to estimate the overall TJDFT rate.

TPU procedural events 237/972: appeal allowed; 239: appeal denied; 238: appeal partially allowed; 235: appeal not admitted for review; 240–242: appeal admitted for review in part. Only documents with a single mapped category across their entire history are included in that category. Repeated events count once per document. Different categories within the same document are ambiguous, even on different dates: no assumption is made about which appeal or party they represent. An appeal's merits outcome is not inferred from a claim being upheld or dismissed, inclusion in G2, or the event's free-text name. Codes outside the mapping are not classified; coverage is limited, and classification is not equivalent to a legal review of the full text.

Binary denominator = documents with appeals allowed + documents with appeals denied. Rates are fractions between 0 and 1. An empty denominator returns null rates. Documents with appeals partially allowed, ambiguous outcomes, appeals not admitted for review or admitted for review in part, unknown outcomes, and documents from other court levels are explicitly listed as exclusions. The outcome filter only selects distribution series, without changing the denominator. analyzed_appeals remains null because we do not identify individual appeals. /api/processes/ exposes the category, evidence codes/dates, and rule version.

Official references consulted on September 18, 2026:

- [SGT/CNJ — procedural event supplements and codes](https://www.cnj.jus.br/sgt/gerenciar_complementos.php).
- [TPU/CNJ Manual, section 6.3.7](https://www.cnj.jus.br/sgt/versoes_tabelas/manual/Manual_de_utilizacao_das_Tabelas_Processuais_Unificadas.pdf): a decision may contain different events for each party; do not add events together as if they were independent decisions.
- [CNJ Glossary — judgment codes](https://www.cnj.jus.br/wp-content/uploads/2016/12/647ce9b3aeafe3f54d3832731c925406.pdf), including code 972.

This implementation replaces the previous notes stating that merits information was unavailable: there is now a per-document indicator with explicit exclusions, but there is still no dimensional fact at the individual-appeal grain.
