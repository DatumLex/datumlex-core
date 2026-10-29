# Instalação local após transferência

Em 29/10/2026, o projeto de `C:\API\datumlex-core` foi transferido para
`D:\DatumLex-Projetos\datumlex-core`, em pasta exclusiva.

Código, configurações, ambiente Python, arquivos coletados, backups e histórico
local acompanham o projeto. O serviço PostgreSQL existente não é recriado nem
tem seu volume movido: a conexão local é preservada pelo `.env`.

Para executar a coleta a partir desta pasta:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\collect.ps1 -Target 20000
```

A tarefa `DatumLex-Local-5400D7A3` é atualizada para o caminho novo; não é
criada uma segunda tarefa com outro nome. As demais instalações não são alteradas.
As instruções de instalação após clone estão em `COLETA-20000.md`.

O D: utiliza FAT32. Novos resultados NLP ficam distribuídos em
`runs/<execução>/results/<prefixo>/`, evitando excesso de arquivos por pasta.
Parte dos resultados históricos da transferência fica preservada em
`backend/data/backups/historico-nlp-transferencia.zip`, com relatório de
verificação ao lado. Arquivos históricos já transferidos permanecem nas
pastas originais. O arquivo compactado contém o restante, com caminhos
relativos ao projeto; não é necessário extraí-lo para novas coletas.

A verificação do ZIP confirmou 49.947 arquivos e 497.523.308 bytes.
A remoção recursiva dos remanescentes históricos no C: foi bloqueada
pela revisão automática de segurança. Esses remanescentes permanecem
na origem, sem serem usados pela instalação ativa no D:.
