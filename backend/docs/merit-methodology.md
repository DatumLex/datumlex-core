# Regra atual: tpu-document-latest-v2

O resultado selecionado é o movimento mapeado com maior occurred_at por documento. Em empate, vence o maior ID local de process_movement (desempate técnico solicitado, não precedência jurídica). Movimentos sem data não disputam a seleção; sem resultado datado o documento é desconhecido. Movimentos posteriores não relacionados a resultado não alteram a classificação. O histórico misto não exclui mais documentos. Se o resultado selecionado for parcial ou não conhecido, continua fora da base binária. selected_evidence expõe código, data e ID usados. Os IDs são locais e podem mudar numa recarga dos movimentos.

A base, filtros e limitações por documento continuam iguais. A regra anterior abaixo é mantida apenas como histórico e foi substituída.

# Taxas por documento — tpu-document-v1

Indicador exploratório, calculado sobre documentos DataJud em G2/TR, não uma contagem de recursos individuais. A unidade do modelo dimensional continua sendo source_id. A consulta usa data de ajuizamento, não de julgamento. A extração local é parcial e não permite estimar a taxa geral do TJDFT.

Movimentos TPU 237/972: provimento; 239: desprovimento; 238: parcial; 235: não conhecimento; 240–242: conhecimento parcial. Somente documentos com uma única categoria mapeada em todo o histórico entram na respectiva categoria. Movimentos repetidos contam uma vez por documento. Categorias diferentes no mesmo documento são ambíguas, mesmo em datas diferentes: não se presume qual recurso ou parte representam. Não se infere mérito de procedência, improcedência, presença em G2 ou nome livre do movimento. Códigos fora do mapa não são classificados; a cobertura é limitada e a classificação não equivale à revisão jurídica do inteiro teor.

Base binária = documentos providos + documentos desprovidos. Taxas são frações entre 0 e 1. Base vazia retorna taxas null. Parciais, ambíguos, não conhecidos/conhecimento parcial, desconhecidos e outras instâncias são explicitados como exclusões. O filtro outcome só seleciona séries da distribuição, sem alterar a base. analyzed_appeals permanece null, pois não identificamos recursos individuais. /api/processes/ expõe categoria, códigos/datas de evidência e versão da regra.

Referências oficiais consultadas em 18/09/2026:

- [SGT/CNJ — complementos e códigos dos movimentos](https://www.cnj.jus.br/sgt/gerenciar_complementos.php).
- [Manual TPU/CNJ, item 6.3.7](https://www.cnj.jus.br/sgt/versoes_tabelas/manual/Manual_de_utilizacao_das_Tabelas_Processuais_Unificadas.pdf): uma decisão pode conter movimentos distintos por parte; não somar movimentos como se fossem decisões independentes.
- [Glossário CNJ — códigos de julgamento](https://www.cnj.jus.br/wp-content/uploads/2016/12/647ce9b3aeafe3f54d3832731c925406.pdf), incluindo o código 972.

Esta implementação substitui as notas anteriores de mérito indisponível: agora há um indicador por documento com exclusões explícitas, mas ainda não há fato dimensional no grão de recurso individual.
