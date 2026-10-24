# ETL do DatumLex

Integração STJ: consulte [arquitetura, linhagem, execução e limites](STJ-ARCHITECTURE.md).
`run.py --court STJ` coleta metadados; `stj_documents.py` coleta textos oficiais.
`pangea.py` importa precedentes públicos do STJ pelo Pangea.

## Coleta Pangea

Com o mesmo ambiente e banco configurados abaixo, execute na pasta `etl/`:

```powershell
.venv/Scripts/python.exe pangea.py --query "responsabilidade civil" --page-size 100 --max-pages 5
```

O comando consulta até cinco páginas e registra cobertura, origem e contadores
em `PangeaImportRun`. Consulte `pangea.py --help` para ajustar os limites.
As referências importadas ficam pendentes de aprovação jurídica e não criam
automaticamente vínculos de aderência. O ponto de entrada reutiliza o comando
`sync_pangea` do backend, assim como `run.py` reutiliza `extract_datajud`, sem
duplicar as regras de transformação ou os modelos. Não há agendamento automático.

Ponto de entrada separado para executar **DataJud → validação e normalização →
banco dimensional**, sem iniciar o servidor do backend ou o frontend.

O processo e o ambiente Python são separados. O código de extração, as regras de
transformação, os modelos Django e as migrações continuam no `backend/`, para
evitar duplicação. Esta pasta precisa permanecer ao lado dele no mesmo checkout;
não é um pacote independente do código do backend.

## Preparação no Windows

Requer Python 3.12+ e um banco já preparado pelas migrações do backend.
No PowerShell, a partir da raiz de `datumlex-core`:

```powershell
cd etl
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edite `etl/.env` para informar a chave pública do CNJ e, se necessário, o
`DATABASE_URL`. Não sobrescreva um `.env` já configurado. A precedência é:
variáveis do processo → `etl/.env` → `backend/.env` → padrões do Django.
Sem `DATABASE_URL`, o padrão existente é `backend/data/datumlex_v2.sqlite3`.
Para compartilhar os resultados com o dashboard, use o mesmo banco do backend.
Endereços Docker como `db` só funcionam dentro da rede Docker; uma execução no
Windows deve usar o host e a porta publicados pelo banco.

Esta entrada não inicia banco, não aplica migrações e não cria usuários.
Se o banco ainda não estiver preparado, siga o procedimento do backend antes
de executar a carga.

## Execução

Consultar opções (não faz extração):

```powershell
.venv/Scripts/python.exe run.py --help
```

Extrair uma amostra limitada a duas páginas de cem documentos:

```powershell
.venv/Scripts/python.exe run.py --subjects 10431,10433,10439 --start 2023-01-01 --page-size 100 --max-pages 2
```

A data final omitida assume o dia da execução. Os códigos de assuntos são
explícitos; descendentes não são incluídos automaticamente.

Continuar uma extração pausada ou com falha, usando o ID mostrado na saída:

```powershell
.venv/Scripts/python.exe run.py --resume 1 --max-pages 5
```

Importar uma resposta DataJud local com `hits.hits`:

```powershell
.venv/Scripts/python.exe run.py --input data/sample.json --subjects 10433
```

Caminhos relativos de entrada são resolvidos a partir da pasta atual do terminal.
Os arquivos de dados e credenciais locais são ignorados pelo Git.

## Limites e operação

- DataJud público: TJDFT por padrão; use `--court STJ` para STJ. Os textos oficiais
  do STJ têm coletor próprio e não entram automaticamente nos indicadores.
- Execute uma carga por vez contra o mesmo banco.
- O padrão limita cada invocação a cinco páginas. `--max-pages 0` percorre até
  a API retornar uma página vazia e pode realizar uma carga extensa.
- O estado `paused` pode encerrar com código de saída zero: consulte o estado
  impresso antes de considerar a extração completa.
- Retomada de carga interrompida não é uma política de atualização incremental
  periódica dos registros antigos.
- O progresso e o cursor ficam no banco, no modelo `ExtractionRun` existente.
- Não há agendamento automático ou Prefect instalado nesta etapa. Um agendador
  futuro pode chamar o Python desta pasta com o caminho absoluto de `run.py`.
- As migrações permanecem sob responsabilidade do backend; mudanças de esquema
  precisam ser coordenadas com o ETL.

As regras e limitações da extração estão documentadas em `../backend/README.md`.
