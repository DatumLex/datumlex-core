# Pangea: dez tribunais

O importador `sync_pangea` aceita STJ, TJDFT, TJSP, TJMG, TJRJ, TJRS,
TJPR, TRF1, TRF3 e TST. Os dez sao o padrao. A pesquisa publica disponibiliza
as siglas TJDF, TRF01 e TRF03, convertidas para os codigos locais sem alterar
as siglas guardadas na proveniencia. A selecao e validada contra o catalogo
publico; respostas de outro tribunal geram falha explicita.

Comando manual, a partir da raiz do clone:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\collect-pangea.ps1
```

O padrao pesquisa responsabilidade civil em ate dez paginas de cem registros
(ate 1.000 resultados por chamada, nao necessariamente 1.000 novos registros).
Todas as especies disponibilizadas pelo catalogo sao pesquisadas, exceto
cancelados. A busca retorna referencias/teses de precedentes, nao inteiro teor
de acordaos nem doutrina. Pode haver tribunais sem resultados para um termo.

Para um subconjunto ou pagina posterior:

```powershell
.\scripts\collect-pangea.ps1 -Courts 'TJSP,TJMG' -StartPage 10
```

As paginas de `StartPage` sao zero-based. A execucao registra `start_page`,
`next_page`, tribunais, termo, tamanho e limite no historico Pangea. Na retomada,
use `next_page` mantendo termo, tribunais e tamanho de pagina da execucao
anterior. Repetir uma pagina nao duplica a mesma referencia da mesma fonte.
A ordenacao da busca pode mudar com atualizacoes do Pangea; a paginacao nao
constitui snapshot imutavel nem censo historico.

A data `ultimaAtualizacao` permanece como atualizacao da fonte. Nao e usada
para afirmar julgamento/publicacao entre 2016 e hoje. Referencias sem data
juridica sao identificadas como periodo nao confirmado nos relatorios.
Nao foram definidos dez assuntos estatisticamente mais comuns nesta alteracao.

O wrapper exige banco local. Os relatorios Pangea respeitam os tribunais
selecionados. Referencias importadas permanecem pendentes de revisao juridica;
esta ampliacao nao cria avaliacoes de aderencia ou divergencia.

A alteracao nao inicia coleta, nao reativa tarefas e nao publica no Render.
