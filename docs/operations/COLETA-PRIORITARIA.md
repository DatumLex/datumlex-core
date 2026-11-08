# Coleta prioritaria: doutrina e jurisprudencia

A rotina busca primeiro artigos de doutrina, depois retoma a jurisprudencia.
Pangea nao participa desta carga. Usa o banco local e os dez temas iniciais de
Responsabilidade Civil do acervo; a descoberta de doutrina filtra titulos
bibliograficos relacionados a responsabilidade civil e temas de reparacao.

A partir da raiz do clone, apos `scripts/setup.ps1 -Migrate`:

```powershell
.\scripts\collect-priority.ps1 -DoctrineLimit 50 -JurisprudenceTarget 20000
```

Doutrina: consulta ate 44 sumarios oficiais RIL/Senado, de 2016 ate o trimestre
atual, e inspeciona ate 600 paginas de artigos. Seleciona ate 50 novos candidatos
com titulo pertinente, data entre 2016 e hoje e PDF declarado nos metadados.
Downloads mantem limites de tamanho e guardam texto por pagina, bibliografia e
hashes. O limite nao garante 50 artigos disponiveis ou extraiveis. Paginas sem
metadados, PDFs sem texto extraivel e fontes indisponiveis ficam registrados.
Noticias e revistas inteiras nao sao contadas como artigos nesta descoberta.

Jurisprudencia: busca TJDFT por responsabilidade civil em lotes de ate 1.000,
com retomada e limite de 20.000 textos completos unicos ja arquivados. Processa
NLP e importa apos cada lote. Outras fontes de jurisprudencia nao sao ampliadas
por esta rotina. Referencias tematicas sao candidatas e continuam pendentes de
revisao; nao existe garantia de cobertura completa em todos os anos.

O acervo por assunto e atualizado apos as importacoes. A rotina registra estado
em `backend/data/operations/priority-collection.json`; a descoberta tem seu
proprio estado em `doctrine/discovery.json`. Falhas nao sao contadas como coleta
bem sucedida. Reexecutar o mesmo comando retoma documentos/paginas ja salvos.
A rotina nao reativa agendamentos diarios nem publica no Render.
