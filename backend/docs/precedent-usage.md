# Identificação automática de uso de precedentes

`GET /api/precedent-usage/?court=TJDFT&start=2016-01-01&end=2026-11-12`

A mesma função alimenta `statistics.precedent_usage`, a aba Precedentes e o PDF.
Requer sessão e acesso a todos os tribunais solicitados. Aceita `subject`, `page`
e `page_size` (1 a 100). Página vazia não altera as contagens globais.

## O que é medido

A versão `ementa-explicit-stj-v1` identifica referências explícitas a súmulas e
temas do STJ na ementa do próprio documento judicial. Não decide mérito nem
comprova aderência material. Não exige validação dos desenvolvedores e não
cria ou aprova `DecisionAssessment` nem revisões NLP.

O denominador contém pares distintos documento/precedente classificados como
`applied` ou `not_applied`. O numerador contém `applied`. Simples citações e
ambiguidades não integram a taxa. Afastamento pode ser juridicamente correto;
não é contado como divergência. Sem denominador, a taxa é `null`; o cartão do
PDF mostra a quantidade de referências identificadas, incluindo contextos
ambíguos, em vez de fabricar uma porcentagem.

## Evidência e limites

Cada resultado contém o trecho exato, offsets e linha do texto original, URL
HTTPS judicial, versão do texto, SHA-256, versão da regra e identificador
determinístico da evidência. Repetições do mesmo par não multiplicam a base;
indicações contraditórias ficam como ambíguas. Usa a versão de texto mais
recente, conferindo seu hash e identidade da fonte. O cálculo é uma projeção
somente de leitura: não modifica os textos nem o banco real.

A ementa é delimitada por cabeçalhos explícitos; relatórios, votos e precedentes
transcritos fora dela não entram. Atribuições às partes, aspas, várias autoridades
no contexto local, hipóteses e negações ambíguas provocam abstenção. Essa regra
conservadora pode deixar de identificar aplicações existentes. Referências sem
tribunal explícito, como "Tema 970", não recebem STJ por suposição. Não há
verificação automática de vigência, correção ou aplicabilidade jurídica do tema.

O período usa data de julgamento, diferente do ajuizamento DataJud. Sem data
não há inclusão. Assunto TPU exige correspondência explícita nos metadados;
classificação lexical não substitui essa correspondência. O filtro de resultado
DataJud não é aplicado a esta população e é sinalizado como tal. Inventários
Pangea, extratos de publicação e doutrina não entram como decisões judiciais.
Exclusões e cobertura são devolvidas separadamente.

## Validação

`python -m pytest tests/test_precedent_usage.py tests/test_report_nlp.py tests/test_historical_report.py`

Os exemplos dos testes são sintéticos e existem apenas no banco temporário de
testes. Nenhum exemplo é importado para o corpus público ou banco de uso real.
