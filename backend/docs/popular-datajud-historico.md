# Popular DataJud manualmente e verificar textos para NLP

Período padrão: **01/01/2016 até hoje**, no horário de São Paulo.
Tribunais padrão: **STJ, TJDFT, TJSP, TJMG, TJRJ, TJRS, TJPR, TRF1, TRF3 e TST**.

O script está em `tools/popular_datajud_historico.py`. Usa o código e o `.env`
do projeto indicado por `--projeto`, sem alterar o frontend ou a branch.
Requer PostgreSQL/Docker em funcionamento. O banco de origem padrão é
`datumlex_backup_review_20261113`, já restaurado do ZIP antigo de 11/11.

## 1. Conferir antes de gravar

Abra o PowerShell e execute o bloco completo:

```powershell
$pasta = 'C:\Users\abima\OneDrive - Fatec Centro Paula Souza\Documentos\ChatGPT\APIDatumLex 2'
$projeto = Join-Path $pasta 'datumlex-core'
$python = Join-Path $projeto 'backend\.venv\Scripts\python.exe'
$comando = Join-Path $projeto 'tools\popular_datajud_historico.py'
& $python -X utf8 $comando --projeto $projeto --nlp
```

Sem `--gravar`, o comando apenas apresenta o plano e verifica os textos. Não
coleta pela internet nem altera o banco. O relatório mostra os dez tribunais,
os dez temas canônicos e a distribuição dos registros do backup por ano.

## 2. Recuperar o backup e executar NLP somente onde houver texto apto

```powershell
& $python -X utf8 $comando --projeto $projeto --gravar --nlp
```

O comando recupera apenas registros DataJud públicos com origem registrada,
revalida-os pelo normalizador do projeto e usa seu carregador oficial. Ignora
identificadores já existentes no destino. Preserva o banco de origem e registra
que a nova carga veio de um snapshot, incluindo IDs e status das execuções
originais. O snapshot pode conter uma execução originalmente ainda parcial.

O backup conhecido tem dados DataJud de 2023 em diante, principalmente TJDFT e
STJ. Recuperá-lo não cria registros de 2016–2022 ou dos demais tribunais.

## 3. Também coletar de 2016 até hoje nos dez tribunais

```powershell
& $python -X utf8 $comando --projeto $projeto --gravar --coletar --nlp --paginas 20
```

Esse comando recupera os registros locais primeiro e testa o acesso à API. Se
a fonte não responder, preserva o que já foi recuperado e informa os tribunais
pendentes. Se responder, usa `extract_datajud` para cada um dos dez tribunais.
Cada execução consulta no máximo 20 páginas de 100 registros por tribunal.
É uma rodada limitada, não uma promessa de cobertura integral. Repetir o mesmo
comando retoma as execuções remotas pausadas/falhas com o mesmo escopo.
O processo precisa de internet e de `DATAJUD_API_KEY` configurada no backend.

Para coletar sem ler o backup:

```powershell
& $python -X utf8 $comando --projeto $projeto --gravar --sem-backup --coletar --nlp
```

Para um primeiro lote de recuperação limitado:

```powershell
& $python -X utf8 $comando --projeto $projeto --gravar --limite-recuperacao 100 --nlp
```

## Mesmo padrão do projeto

- Importa os dez tribunais de `ACTIVE_COURTS`, sem uma segunda lista independente.
- Usa os códigos CNJ de `DEFAULT_DATAJUD_SUBJECT_CODES` e o normalizador existente.
- Usa os mesmos dez temas, IDs, nomes e regras de `src.nlp.topics.TOPICS`.
- Mantém códigos CNJ e temas lexicais em classificações separadas.
- Valida sigilo, tribunal, número CNJ, data, códigos e identidade antes da carga.
- Mantém movimentos e as regras de resultados já implementadas pelo projeto.
- Registra rejeições em vez de inventar campos ou classificações.
- Não reprocessa textos cuja mesma versão já tenha NLP completo ou parcial.

## Limite do NLP

**DataJud fornece metadados, não o inteiro teor necessário para extrair teses.**
`--nlp` procura versões textuais já cadastradas no projeto e ainda sem NLP
concluído. Exige data dentro do período e verificação dos arquivos originais.
Sem texto original disponível, informa a lacuna e não fabrica uma extração.
O ZIP do banco não contém automaticamente os PDFs/JSONs/TXTs externos.

Use `--raiz-textos 'CAMINHO\backend\data\operations'` se os originais estiverem
em outra pasta. O limite padrão de novos textos NLP por rodada é 100; ajuste
com `--limite-nlp`, até 1000. Saídas permanecem com revisão jurídica pendente.
Não é realizada uma nova coleta de inteiro teor por este script.

## Relatórios e retomada

Cada execução com gravação tem sua própria pasta:
`backend/data/operations/manual-datajud/<id>/`, com relatório, rejeições e logs
NLP quando aplicável. As páginas DataJud usam o cursor transacional já existente.
A recuperação ignora IDs salvos em uma execução anterior. Não execute em paralelo
uma rotina de importação que desconsidere as travas ETL do projeto.

Para uma rodada por ano, use `--inicio AAAA-01-01 --fim AAAA-12-31`;
no ano atual, o fim deve ser no máximo hoje. Sem `--nlp`, a rodada coleta apenas
os metadados que alimentam a Visão geral. O arquivo local
`backend/data/operations/datajud-skip-year-AAAA.flag` cancela uma rodada anual
pendente daquele ano. Remova-o para reativar o ano. Não é enviado ao GitHub.

Código de saída 2 indica falha na coleta remota ou no NLP: examine o relatório.
O script não apaga tabelas, não restaura um banco sobre outro e não substitui
credenciais. Ele requer que o banco de destino já tenha as migrações aplicadas.
