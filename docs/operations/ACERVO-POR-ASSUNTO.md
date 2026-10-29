# Acervo por assunto

A aba inicial Acervo por assunto separa jurisprudencia, precedentes e doutrina.
A selecao inicial reune os tribunais autorizados do perfil; pode ser reduzida
no seletor de tribunais.
Usa documentos efetivamente importados no banco local, nao apenas arquivos
baixados ou linhas de metadados DataJud. Os tres grupos possuem contagens,
fontes, datas, formato do conteudo e revisao identificados.

Os dez temas iniciais de Responsabilidade Civil sao dano moral, dano material
e reparacao integral, saude, transito, negativacao indevida, transporte aereo,
entrega de imovel, imagem/honra/privacidade, perda de uma chance e internet.
A selecao e editorial e nao corresponde a ranking nacional dos mais comuns.

Assuntos com documentos nos tres tipos aparecem primeiro. O filtro de cobertura
completa exige tres contagens positivas. Isso nao comprova que as fontes se
referem ao mesmo caso nem estabelece aderencia juridica entre elas. A classificacao
por termos no texto ou na bibliografia e candidata, pendente de revisao.

Jurisprudencia e precedentes respeitam os tribunais autorizados e selecionados.
Doutrina e bibliografia compartilhada, sem tribunal ficticio. O periodo e de
julgamento ou publicacao quando informado. Referencias sem data podem ser
incluidas explicitamente e ficam sinalizadas como periodo nao confirmado.
O filtro de assunto CNJ da visao geral nao substitui os assuntos desta aba.

Um documento pode constar de varios temas, mas conta uma vez por categoria
no recorte. Ementa, inteiro teor e publicacao sao identificados separadamente.
A consulta tem paginacao e busca por titulo; nao oferece busca integral do texto.
A exportacao PDF preexistente continua nas outras abas e nao exporta este acervo.

O indice e reconstruivel, separado do historico imutavel de evidencias NLP.
Reindexacao local, a partir de backend:

```powershell
.\.venv\Scripts\python.exe manage.py refresh_legal_corpus
```

O comando nao acessa APIs externas e atualiza apenas registros alterados.
Importacoes futuras de resultados NLP e Pangea atualizam suas categorias no indice.
Depois de importar nova doutrina, execute o comando acima ou use
`--category doctrine`. Textos locais de doutrina so sao usados quando o caminho
e o hash do texto conferem; caso contrario, apenas a bibliografia e considerada.

A API GET `/api/corpus/` exige login e autorizacao dos tribunais. Parametros:
court, start, end, topic, category, page, page_size (1..50), q (titulo),
include_undated e complete_only (true/false). Datas limitadas a 2016..hoje.

Esta implementacao nao reinicia coletas, nao redefine o banco e nao publica
no Render. A proporcao 80/15/5 nao e imposta como cota de dados.
