# Escopo ativo e cobertura de jurisprudência

Esta configuração substitui os totais e o escopo dos relatórios de ampliação anteriores. A aplicação e as novas coletas ficam limitadas a:

**STJ, TJDFT, TJSP, TJMG, TJRJ, TJRS, TJPR, TRF1, TRF3 e TST.**

A lista é uma prioridade definida para o projeto; não é um ranking oficial. O catálogo técnico conserva os aliases oficiais conhecidos para referência, mas os comandos, a seleção analítica, as permissões exibidas e a automação usam somente os dez ativos.

## Acervo ativo verificado

| Tribunal | Inteiro teor | Ementas | Publicações de acórdão |
|---|---:|---:|---:|
| TJDFT | 1.275 | 0 | 0 |
| STJ | 3 | 350 | 1 |
| TST | 0 | 50 | 0 |
| TJSP, TJMG, TJRJ, TJRS, TJPR, TRF1, TRF3 | 0 | 0 | 0 |
| **Total** | **1.278** | **400** | **1** |

São **1.679 documentos únicos ativos**, com fontes arquivadas e hashes conferidos. O inteiro teor TJDFT tem documentos de cada ano de 2016 a 2026: houve uma coleta inicial de 275 e uma ampliação de mais 1.000, sem exclusões nessa rodada. A distribuição é uma amostra de pesquisa pública por responsabilidade civil, não um censo do tribunal. As ementas TST usam pesquisa por dano moral. Publicações DJEN conservam o tipo publication_excerpt; não são contadas como julgamento completo.

As 816 referências Pangea são contadas separadamente. DataJud não entregou novos documentos na execução inicial desta instalação. Cadastro, endpoint conhecido, resposta vazia ou ausência de acórdão na primeira página não comprovam cobertura — nem ausência de jurisprudência — de um tribunal. Ainda não há jurisprudência adquirida dos outros sete tribunais ativos.

Relatório verificável: `backend/data/operations/coverage-by-court.json`, com presença e lacunas por tribunal, tipo e ano.

## NLP e importação

O pipeline 0.3.0 recebe inteiro teor STJ/TJDFT, ementas oficiais STJ/TST e publicações DJEN identificadas como acórdãos. Os adaptadores verificam artefato, hash do texto, identificador, tipo de conteúdo e tribunal retornado. O tipo não é convertido silenciosamente: ementas e publicações recebem aviso de contexto incompleto e não entram no denominador de decisões completas do painel nem no benchmark de inteiro teor.

O extrator continua sendo experimental por regras. Não é uma classificação semântica validada para todos os ramos do direito. Evidências e resultados permanecem pendentes de revisão jurídica; não foi criada uma aprovação humana ou liberação de qualidade.

A importação ignora a repetição de um resultado quando somente o hash da fila global muda, mantendo origem, texto, parâmetros, código e anotações iguais. A conferência final ignorou **1.679 resultados inalterados**, sem criar outras extrações. As versões antigas necessárias à auditoria permanecem no banco.

## Automação

O agendamento local existente permanece às 19h40. A rodada usa um orçamento nominal de até 1.000 registros selecionados entre etapas: até 200 metadados DataJud, 300 textos TJDFT, até 455 resultados de consultas DJEN e 45 ementas STJ/TST. Com apenas dez tribunais ativos e amostra DJEN de cinco registros por tribunal, a etapa DJEN consulta atualmente até 50 registros; o limite é um teto, não promessa de 1.000 documentos novos. Duplicatas, filtros de elegibilidade, indisponibilidade e ausência de resultados podem reduzir o incremento. Referências Pangea não são somadas como decisões completas. Arquivos de lote STJ podem conter outros registros de origem, mas apenas os selecionados são incluídos na fila.

DataJud gira entre os dez ativos. O coletor TJDFT mantém cursor por ano. DJEN usa uma amostra do dia anterior, com erros e ausência de resultados elegíveis registrados. Não existe coletor validado de inteiro teor para todos os dez tribunais. Não foram contratadas fontes pagas nem feitas publicações na Render.

## Limpeza e preservação

- 81 cadastros fora do escopo, sem vínculo de permissão com usuários, removidos após backup.
- 31 publicações de outros tribunais retiradas da fila ativa e preservadas em arquivo.
- 24 downloads temporários de pesquisa arquivados e removidos da área de trabalho.
- Artefatos de origem referenciados, contas, permissões existentes e histórico imutável de evidências preservados. As extrações antigas fora do escopo não foram apagadas nem tiveram as proteções de auditoria desativadas.
- Junção temporária de dependências frontend removida após as verificações.

## Verificação

Backend: 150 testes executados, 146 passaram e quatro ignorados. Verificação Django sem problemas e sem novas migrações de modelos pendentes. Ferramenta de benchmark: 11 testes passaram. ESLint e build frontend passaram. Os testes usaram bancos isolados e dados sintéticos; eles não constituem validação jurídica do corpus.

Nenhum comando Git, commit ou push foi executado.
