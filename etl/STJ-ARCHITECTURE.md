# STJ: arquitetura, linhagem e limites

Referências consultadas em 15/10/2026:

- https://github.com/DatumLex/documentation/blob/main/architecture/dimensional-model.md
- https://github.com/DatumLex/documentation/blob/main/architecture/data-dictionary.md
- https://github.com/DatumLex/documentation/blob/main/architecture/technology-stack.md
- https://datajud-wiki.cnj.jus.br/api-publica/endpoints/
- https://dadosabertos.web.stj.jus.br/dataset/integras-de-decisoes-terminativas-e-acordaos-do-diario-da-justica

## Fluxo

1. `etl/run.py --court STJ`: DataJud → validação Python → dimensões →
   `fact_resource` → ponte `fact_process_subject` → API Django → dashboard React.
2. `etl/stj_documents.py`: catálogo oficial STJ → metadados filtrados → ZIP
   oficial → textos em `etl/data/stj-documents/texts/` → proveniência em tabelas
   operacionais PostgreSQL. Os arquivos não são servidos publicamente.

O PostgreSQL configurado pelo backend continua sendo a fonte dos dados processados.
O ETL é um processo separado que reutiliza modelos e migrações Django. Não há
segundo warehouse nem cálculo jurídico no frontend.

## Recorte e datas

Ambos os comandos usam `2023-01-01` a `2026-10-15`, inclusivo, e os códigos
explícitos `10431,10433,10439`. Descendentes não são incluídos automaticamente.
Para DataJud, a data é `dataAjuizamento`. Para textos, é `dataPublicacao` no
fuso America/Sao_Paulo. São populações diferentes: uma decisão publicada no
período pode pertencer a processo ajuizado antes dele. Não se afirma equivalência.

O catálogo consultado continha publicações até 08/10/2026: o filtro até 15/10 não
cria documentos para os dias ausentes. O catálogo bruto é salvo para auditoria.
Executar até o fim significa percorrer os lotes disponíveis, não provar cobertura
integral do tribunal. Os ZIPs originais são temporários; somente textos com
assuntos e publicação compatíveis são retidos.

## Mapeamento dimensional DataJud

| Elemento | Regra |
|---|---|
| `dim_process` | `numeroProcesso`, texto de 20 dígitos, preservando zeros; sigilo público 0 |
| `dim_time` | `dataAjuizamento`, ano, mês, dia e trimestre |
| `dim_class` | `classe.codigo/nome`, respeitando limite de 100 caracteres |
| `dim_org` | `orgaoJulgador.codigo/nome`, chave de negócio `(court, code)` |
| `dim_degree` | `grau`, inclusive `SUP`; nunca convertido para inteiro |
| `dim_subject` | `assuntos[].codigo/nome`, códigos positivos, deduplicados |
| `dim_result` | Regras existentes; `SUP` permanece fora do denominador G2/TR |
| `fact_resource` | Um documento DataJud por linha, peso 1; não um recurso individual validado |
| `fact_process_subject` | Par único documento/assunto, sem multiplicar indicadores |

Identificadores de documentos STJ recebem prefixo `STJ:` para evitar colisões
com IDs de outra fonte. O identificador original permanece em `raw_payload`.
As cargas têm tribunal, recorte, cursor, contadores e rejeições em `extraction_run`.
Cada página é confirmada junto com o cursor, em transação. Reexecução atualiza
o documento existente; versão antiga não sobrescreve versão nova.

## Textos e proveniência: extensão operacional

O modelo publicado não define uma entidade completa de textos do STJ. Esta
implementação adiciona uma área operacional de origem, sem mudar o grão da fato:

| Tabela/campo | Origem e significado |
|---|---|
| `stj_document.source_id` | `seqDocumento` do STJ, único |
| `publication_date` | `dataPublicacao`, milissegundos epoch convertidos ao fuso do STJ |
| `metadata` | Registro original selecionado, incluindo `assuntos`, `numeroRegistro` e tipo |
| `metadata_url`, `archive_url` | Recursos JSON e ZIP oficiais do catálogo |
| `local_path` | Caminho relativo do texto retido; não usa caminhos de extração do ZIP |
| `sha256` | Hash dos bytes do texto, para integridade e rastreabilidade |
| `collected_at` | Momento local da coleta |
| `stj_document_batch` | Recorte, hash do recorte, dia publicado e confirmação do lote |

`numeroRegistro` do STJ não é presumido equivalente ao número CNJ. Textos não
são associados automaticamente a fatos e não alteram resultados jurídicos.
Vinculação entre fontes e NLP permanecem etapas futuras com evidência própria.
Um lote com texto ausente registra `scope.missing_document_ids` no PostgreSQL,
continua os demais lotes e termina como PARTIAL se restarem pendências. Repetir
o comando reprocessa esses lotes sem repetir os lotes completos.
O bloqueio de arquivo impede coletores locais simultâneos.
O coletor de textos atualmente usa bloqueio Windows (`msvcrt`).

## Reconciliação com o dicionário publicado

São preservados os ajustes já documentados em `backend/docs/resource-schema.md`:
PK substituta da fato; ponte sem repetir todas as FKs; IBGE ausente como NULL;
número CNJ como texto; códigos de grau como texto. O dicionário remoto contém
divergências (por exemplo `nivelSigilo` como origem de `id_process`, conversão
do número CNJ/grau para inteiro e limites 255 para colunas 100). Não são aplicadas
conversões que corrompam identificadores. A implementação usa `numeroProcesso`
para a dimensão processo e os limites reais do schema Django.

O dicionário cita JurisDF para resultados. A integração atual já usa um proxy
documental TPU explicitamente documentado; esta extensão não o apresenta como
resultado JurisDF nem amplia sua validade ao STJ. Nenhuma aprovação acadêmica
ou revisão formal do modelo é presumida por este documento.

## Execução a partir de `etl/`

Task #99: versões imutáveis dos arquivos e metadados são registradas em
`stj_document_version`; execuções e contadores reconciliáveis em `stj_ingestion_run`.
Datas de julgamento, órgão julgador e tipo/status de precedente permanecem NULL
quando não fornecidos. `--refresh` permite observar revisões de lotes já percorridos.
Arquivos passam a usar ID + hash no nome para preservar conteúdo anterior.
Catálogos são preservados por hash em `data/stj-documents/catalogs/`.
Consulte [evidências e critérios da task](../backend/docs/task-99-evidence.md).

```powershell
.venv/Scripts/python.exe run.py --court STJ --subjects 10431,10433,10439 --start 2023-01-01 --end 2026-10-15 --max-pages 0
.venv/Scripts/python.exe stj_documents.py --subjects 10431,10433,10439 --start 2023-01-01 --end 2026-10-15
```

Antes da primeira execução, aplicar as migrações com o Python de `etl/.venv`
e `backend/manage.py`. As novas migrações são aditivas e preservam os dados TJDFT.
Para retomar DataJud, usar o ID retornado e `run.py --resume ID --max-pages 0`.
Para retomar textos, repetir o mesmo comando. Uma carga por fonte deve estar ativa.
O usuário de suporte vê o STJ no catálogo; os demais precisam de permissão explícita.
