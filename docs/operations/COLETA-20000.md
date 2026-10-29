# Coleta local até 20.000 textos

No Windows, instale Python 3.12 e Node.js/npm. Após clonar, na raiz:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -Migrate
powershell -ExecutionPolicy Bypass -File .\scripts\collect.ps1 -Target 20000
```

O setup cria o ambiente virtual e o `.env` somente se ausentes, gera segredos
locais e instala dependências. Uma instalação nova usa SQLite sem Docker.
Um `.env` existente é preservado; se usar PostgreSQL, inicie esse banco antes.
O segredo de suporte gerado fica em `backend/.env`; não compartilhe esse arquivo.

Para retomar diariamente às 19:40, no horário do Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-schedule.ps1
```

O computador precisa estar ligado, conectado e com o usuário conectado.
Os caminhos são calculados a partir da pasta do clone. A tarefa é identificada
por essa pasta e impede duas execuções simultâneas do coletor de meta.

A meta conta UUIDs únicos de acórdãos públicos com inteiro teor do TJDFT,
na busca por responsabilidade civil entre 2016 e a data atual. Não representa
20.000 processos DataJud, doutrinas, evidências NLP ou cobertura dos dez tribunais.
O corpus existente conta para a meta; esta rotina não apaga o banco.
Cada lote consulta até 1.000 registros, persiste páginas e cursores, executa
NLP e importa resultados locais. Duplicatas não aumentam a meta. O último lote
é limitado ao total solicitado. Ao chegar à meta, chamadas futuras encerram
sem coletar mais documentos.

Falhas temporárias têm tentativas limitadas; após três lotes com falha ou
esgotamento da fonte a rotina para com pendência explícita. Ela não inventa
registros para completar a meta. Execute o mesmo comando para retomar.

Consulte `backend/data/operations/collection-target.json` para estado e contagem,
`tjdft-documents/last-run.json` para a última coleta e
`coverage-by-court.json` para cobertura. Resultados NLP permanecem pendentes
de revisão jurídica. Esta rotina não publica no Render.
