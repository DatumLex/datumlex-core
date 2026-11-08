# Carga complementar dos dez tribunais

STJ, TJDFT, TJSP, TJMG, TJRJ, TJRS, TJPR, TRF1, TRF3 e TST fazem parte
do recorte ativo. A carga complementar pesquisa responsabilidade civil no Pangea
para esses dez tribunais, coleta mais ementas STJ/TST e consulta publicacoes DJEN.
Nao e garantia de inteiro teor ou de cobertura historica em todos os tribunais.

A partir da raiz do clone, depois do setup e das migracoes:

```powershell
.\scripts\collect-other-courts.ps1
```

Pangea: ate dez paginas de cem referencias; siglas sao validadas e normalizadas.
Referencias sem data juridica continuam sem periodo confirmado. O acervo de
precedentes e atualizado apos a importacao, sem aprovacao juridica automatica.

STJ/TST: ate 400 novas ementas por chamada, limitadas a 2016..hoje quando a fonte
informa julgamento. O STJ alterna recursos mensais das turmas civis; o TST mantem
pagina persistente. Paginas parcialmente consumidas sao repetidas, sem duplicar
identificadores. A disponibilidade de arquivos STJ pode comecar depois de 2016;
TST parte dos resultados recentes. A rotina nao declara cobertura anual completa.

DJEN: consulta os ultimos 30 dias, com ate 1.000 registros examinados, distribuidos
entre dez tribunais. Pagina de 25 e cursor por janela/filtro/tribunal. Tipo acordao,
tribunal, data, ausencia de cancelamento e tema civil sao conferidos localmente.
Publicacao de acordao e `publication_excerpt`, nunca inteiro teor. Nao sao
reclassificadas intimacoes ou decisoes de outra natureza para aumentar contagem.

O indice de descoberta recebe novos textos verificados como NLP pendente, sem
criar NlpDocument nem avaliacoes juridicas ficticias. O processador da carga
principal absorve as filas no proximo lote. Esta rotina nao inicia um segundo
escritor NLP. Se a carga principal estiver parada, processe depois com
`tools/nlp_validation/collect_batch.py` ou o fluxo de NLP documentado, evitando
execucoes simultaneas que escrevam a fila global.

Estado: `backend/data/operations/other-courts-collection.json`.
DJEN por tribunal: `djen-documents/multicourt-last-run.json`.
Ementas: `jurisprudence-ementas/last-run.json`.
Falhas ficam registradas e nao impedem tentar as fontes seguintes.
A rotina exige banco local e nao publica no Render nem reativa tarefas diarias.
