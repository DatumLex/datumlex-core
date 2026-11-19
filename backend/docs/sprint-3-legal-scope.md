# Proposta de escopo jurídico do Sprint 3

Versão `0.1.0-draft` · 18/11/2026 · Revisão jurídica e aceite do Product Owner pendentes.

Este documento propõe os primeiros recortes para as histórias [Direito do Consumidor #137](https://github.com/DatumLex/datumlex-core/issues/137) e [Contratos #140](https://github.com/DatumLex/datumlex-core/issues/140). Os códigos são candidatos para revisão nas tarefas [#138](https://github.com/DatumLex/datumlex-core/issues/138) e [#141](https://github.com/DatumLex/datumlex-core/issues/141).

## Códigos candidatos

| Área | Códigos explícitos para a amostra | Regra de revisão |
| --- | --- | --- |
| Direito do Consumidor | `1156` Direito do Consumidor, `7771` contratos de consumo, `6220` responsabilidade do fornecedor, `11974` cláusulas abusivas, `11811` práticas abusivas, `7779` dano moral na relação de consumo, `6226` negativação indevida, `7770` revisão contratual e `7768` rescisão e devolução | Confirmar se a decisão trata da relação de consumo ou de dever específico do fornecedor. Marcar como pendente quando houver somente um código genérico ou quando o regime aplicável estiver em disputa. |
| Contratos | `9580` espécies de contratos, `9587` compra e venda, `9591` empreitada, `9593` locação de imóvel e `9596` prestação de serviços | Confirmar se formação, validade, interpretação, execução, inadimplemento ou extinção de contrato civil ou empresarial é questão central. `7691` inadimplemento e `10582` rescisão ou resolução servem como sinais auxiliares quando associados a uma espécie contratual ou ao texto da decisão. |

Usar os códigos explícitos para recuperar candidatos. Confirmar ascendência, vigência, aplicabilidade por tribunal e descendentes na versão do SGT escolhida para a implementação. Registrar a data da versão e congelar a lista aprovada antes da ingestão. Códigos dos ramos amplos `899` Direito Civil e `7681` Obrigações servem apenas de contexto. Fontes oficiais: [consulta de assuntos do SGT](https://www.cnj.jus.br/sgt/consulta_publica_assuntos.php), [árvore parcial de Consumidor, figura 5](https://www.cnj.jus.br/wp-content/uploads/2021/09/just-pesquisa-maiores-litigantes2018.pdf), [Contratos na tabela estadual, pp. 16–18](https://www.cnj.jus.br/wp-content/uploads/2011/02/tabela-de-assuntos-justia-estadual.pdf) e [inadimplemento e rescisão na tabela de assuntos](https://www.cnj.jus.br/wp-content/uploads/2011/02/tabela-de-assuntos-stf.pdf). As tabelas e a figura servem de referência histórica para os códigos.

## Regras para casos de fronteira

| Situação | Tratamento proposto |
| --- | --- |
| Defeito de produto ou serviço, revisão ou rescisão com fundamento consumerista central | Consumidor como área principal. Registrar Contratos como área secundária quando uma obrigação contratual também for efetivamente analisada. |
| Inadimplemento ou interpretação de contrato civil ou empresarial com pedido acessório de indenização | Contratos como área principal. O pedido de indenização sozinho é insuficiente para incluir o caso em Responsabilidade Civil. |
| Dano decorrente de dever extracontratual, sem questão consumerista ou contratual central | Manter no recorte de Responsabilidade Civil quando atender à política vigente. |
| Códigos de áreas diferentes com ementa inconclusiva, regime jurídico contestado ou texto ausente | Encaminhar à revisão. Registrar a divergência e excluir da população juridicamente confirmada até a decisão do revisor. |
| Contratos administrativos, trabalhistas e relações exclusivamente tributárias; menção incidental a contrato ou ao CDC | Fora dos dois recortes propostos. |

Para comparação entre áreas, propor uma área principal por documento e preservar as secundárias para navegação. Decisões diferentes no mesmo processo conservam sua identidade documental. O aceite jurídico deve confirmar essa regra e o tratamento dos casos em que duas questões centrais coexistem.

## Amostra documental rastreável

Piloto intencional de decisões públicas, com **publicação de 01/01/2023 a 31/12/2025**. Para reproduzir, abra a fonte oficial de cada linha e confira identificador, publicação e ementa. Use o número do processo ou do recurso para repetir a busca no portal do tribunal. As classificações são propostas para revisão e os códigos da decisão devem ser confirmados nos metadados de origem. A amostra foi escolhida para avaliar as fronteiras do recorte. Taxas e cobertura populacional exigem uma amostra adicional.

| Tribunal | Identificador e publicação | Classificação proposta e motivo | Fonte oficial |
| --- | --- | --- | --- |
| TJDFT | Acórdão 1942739 · 0704915-46.2023.8.07.0011 · 26/11/2024 | Consumidor. Dever de notificação antes da inscrição em cadastro restritivo. | [JurisDF](https://jurisdf.tjdft.jus.br/acordaos/d3baad17-8acf-4794-b31a-0a016e297705) |
| STJ | AgInt no AREsp 2609010/PE · registro 202401169140 · 01/10/2024 | Consumidor. Negativação e legitimidade das anotações anteriores para aplicação da Súmula 385. | [Inteiro teor](https://scon.stj.jus.br/SCON/GetInteiroTeorDoAcordao?dt_publicacao=01%2F10%2F2024&num_registro=202401169140) |
| TJDFT | Acórdão 1940127 · 0729396-72.2024.8.07.0000 · 21/11/2024 | Contratos como candidato. Retenção de chaves por inadimplemento e art. 476 do Código Civil. Revisar no inteiro teor eventual questão de consumo. | [JurisDF](https://jurisdf.tjdft.jus.br/acordaos/13b10cd6-2429-4d0a-9d8f-27c90b677546) |
| STJ | REsp 2100351/PR · registro 202303534895 · 27/11/2025 | Contratos. Rescisão de locação comercial e cláusula penal. O recurso foi conhecido parcialmente, informação a preservar ao revisar o desfecho. | [Inteiro teor](https://scon.stj.jus.br/SCON/GetInteiroTeorDoAcordao?dt_publicacao=27%2F11%2F2025&num_registro=202303534895) |
| TJDFT | Acórdão 1693031 · 0718349-74.2019.8.07.0001 · 05/05/2023 | Sobreposição. A decisão examina a relação de consumo e resolve a empreitada por desconformidades técnicas. Proposta de Consumidor como principal e Contratos como secundária. | [JurisDF](https://jurisdf.tjdft.jus.br/acordaos/326f1e24-eff2-48fd-ac7a-d2bef026870c) |
| STJ | AREsp 2747517/PR · registro 202403495024 · 23/10/2025 | Sobreposição. Empreitada residencial e indenização com aplicação do CDC na origem. Preservar a distinção entre o fundamento da origem e a decisão do STJ. | [Inteiro teor](https://scon.stj.jus.br/SCON/GetInteiroTeorDoAcordao?dt_publicacao=23%2F10%2F2025&num_registro=202403495024) |

## Populações e checagens de cobertura

- **Metadados processuais.** Consultar o DataJud por tribunal e lista de códigos, com `nivelSigilo = 0`. Para a sondagem inicial, usar `dataAjuizamento` de `2023-01-01T00:00:00Z` até `2026-01-01T00:00:00Z` exclusivo. Reportar a unidade como registros do índice. A janela de ajuizamento e a janela de publicação do acervo textual respondem a perguntas distintas.
- **Texto e desfechos.** Contar decisões únicas com fonte e data identificáveis. Publicar, por área e tribunal, quantos registros têm classificação confirmada, quantos estão pendentes e quantos têm desfecho elegível. Na taxa binária, manter a regra de elegibilidade do [método de desfechos](merit-methodology.md) e explicitar os casos excluídos.
- **Teses e vínculos.** Medir documentos elegíveis, documentos com evidência de tese e documentos com vínculos confirmados. Registrar a entidade vinculada, a origem do vínculo, a regra utilizada e a revisão. A citação da mesma súmula em dois acórdãos indica um tema em comum e exige verificação antes de contar como vínculo entre registros.
- **Reprodução por caso.** Consultar o [endpoint oficial](https://datajud-wiki.cnj.jus.br/api-publica/endpoints/) com o número CNJ sem pontuação quando disponível. Para o STJ, localizar primeiro o número CNJ correspondente ao registro oficial e verificar a correspondência. Registrar data da consulta, código de assunto retornado, identificador da fonte e eventuais divergências. Ausência de resposta ou correspondência fica como cobertura desconhecida.

Em 18/11/2026, a chave configurada recebeu HTTP 401 nas quatro consultas. Com a chave pública do [CNJ](https://datajud-wiki.cnj.jus.br/api-publica/acesso/), as consultas de total excederam 30 s. A sondagem com `size: 0`, `track_total_hits: 1` e `terminate_after: 1` excedeu 12 s no TJDFT e retornou HTTP 429 no STJ para as duas áreas. A disponibilidade documental foi verificada nas fontes acima. A cobertura de metadados do DataJud segue sem confirmação.

## Critérios para concluir #138 e #141

- [ ] Confirmar a lista de códigos e descendentes no SGT vigente, registrar a versão e revisar as exclusões.
- [ ] Ampliar a amostra com casos positivos, negativos e ambíguos em cada área e tribunal. Revisar a classificação com um profissional jurídico e registrar divergências.
- [ ] Confirmar cobertura por fonte, campo de data e área. Registrar o cruzamento de cada caso amostrado e a cobertura de teses, desfechos e vínculos.
- [ ] Registrar limites, população de cada métrica e aceite jurídico e do Product Owner. A versão aprovada servirá de entrada para [#139](https://github.com/DatumLex/datumlex-core/issues/139) e [#142](https://github.com/DatumLex/datumlex-core/issues/142).
