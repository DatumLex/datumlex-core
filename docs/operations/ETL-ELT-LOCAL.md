# ETL/ELT local: originais, processamento e consulta

O fluxo hibrido preserva o material original em arquivos antes de transforma-lo
para o PostgreSQL. O controle operacional fica em SQLite; isso nao substitui o
banco de consulta nem o historico imutavel de evidencias.

## Execucao apos clone

Instale Python 3.12, Node/npm e execute `scripts/setup.ps1 -Migrate`.
Uma instalacao nova pode usar SQLite local; PostgreSQL exige servico iniciado e
configurado no `.env`. Nenhum segredo do autor do projeto acompanha o clone.

Para um ciclo completo, a partir da raiz:

```powershell
.\scripts\run-etl.ps1 -Mode all -Once
```

Para desacoplar coleta de NLP, execute em dois terminais:

```powershell
.\scripts\run-etl.ps1 -Mode collect -Target 20000 -BatchSize 1000
.\scripts\run-etl.ps1 -Mode process -Follow
```

O segundo acompanha as entradas arquivadas e conclui o material restante depois
que o coletor termina. A meta e de textos completos unicos TJDFT, nao da soma de
todos os tipos nem de cobertura completa dos dez tribunais. Os demais coletores
possuem limites por chamada e podem ter lacunas de disponibilidade.

Para reprocessar somente fontes ja arquivadas, sem coletar pela rede:

```powershell
.\scripts\run-etl.ps1 -Mode process -Once
.\scripts\run-etl.ps1 -Mode process -Sources 'doctrine,pangea' -Once
```

`-Sources` aceita doctrine, pangea, tjdft, ementas e djen. A primeira coleta de um
acervo vazio e incremental: o processamento pode iniciar com o primeiro lote.
Inicie o coletor antes do processador em modo Follow.

## Etapas e garantias

1. Coletar: originais JSON/HTML/PDF, URLs, datas e identificadores. A escrita e
   atomica, com flush antes da publicacao; fonte valida e indice salvo precedem
   o avanco do cursor. Respostas Pangea sao arquivadas com bytes HTTP originais;
   o indice cumulativo evita perder paginas quando a coleta anda mais rapido.
2. Processar offline: conferir hashes, extrair texto de PDFs, padronizar campos,
   rejeitar entradas sem requisitos e importar com transacoes pequenas. PDFs sem
   extracao confiavel permanecem arquivados como pendencias de outra extracao;
   nao sao contados como doutrina com texto extraido.
3. NLP: fila e resultados isolados por UUID de execucao. O arquivo original e
   verificado antes de reutilizar um resultado. Mudancas de texto, fonte, regras,
   prompt, parametros, modelo ou codigo invalidam a chave de computacao.
4. Consulta: indice tematico com contagens separadas, fontes e estado de revisao.
   Conteudo coletado ainda sem NLP pode aparecer com sinalizacao de pendencia.
   Nenhuma etapa cria aprovacao juridica automatica.

O cache e particionado para o FAT32 do D: e mantem resultados imutaveis. A primeira
execucao prepara essa camada; depois reaproveita calculos de documentos inalterados.
O NLP nao mantem todas as anotacoes do acervo em memoria: grava documento a documento.
Cada execucao preserva manifestos e uma copia do codigo/prompt usados.

Falhas ficam no historico, com etapa, horario, codigo de saida e caminhos de logs.
Reexecutar retoma cursores e permite consumir arquivos antes coletados. Jobs
interrompidos sao identificados quando o lock correspondente fica disponivel.
Timeout encerra a arvore de processos criada pela etapa, evitando filhos orfaos.
Locks por papel e fonte evitam duas gravacoes concorrentes do mesmo recurso.
Arquivos originais incompletos sao preservados antes do reparo em nova coleta.

## Estado operacional

- `backend/data/operations/etl-collect.json`: coletor e contagem TJDFT.
- `backend/data/operations/etl-process.json`: importacao/NLP e fila em andamento.
- `backend/data/operations/etl-state.sqlite3`: historico de jobs e etapas.
- `backend/data/operations/etl-logs/<job>/`: saida e diagnostico por etapa.
- `backend/data/operations/nlp-local/jobs/<uuid>/`: entradas e resultados isolados.
- `backend/data/operations/nlp-local/computation-cache/`: calculos reutilizaveis.

O modo all e sequencial; os papeis collect/process permitem execucao desacoplada.
Os comandos antigos collect_batch, collect_priority e collect_until_target passam
pelo novo orquestrador. A tarefa diaria permanece desativada ate solicitacao.

## Limites preservados

DJEN fornece publicacoes recentes de acordaos, nao inteiro teor nem historia desde
2016. STJ/TST incluem ementas; DataJud continua sendo metadado. Pangea fornece
referencias de precedentes com data juridica muitas vezes ausente. Doutrina so
entra como texto extraido quando a extracao e verificavel. Os dez assuntos sao
uma selecao editorial com classificacao lexical candidata, nao ranking nacional.
O fluxo continua local e nao publica no Render. Nao migra o volume Docker do banco.
