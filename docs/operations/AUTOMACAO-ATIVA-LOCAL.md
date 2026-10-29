# Automação local configurada

Configuração feita em 28/10/2026 para esta instalação, sem commits ou push.

- Projeto: `C:/API/datumlex-core`.
- Ambiente Python próprio: `backend/.venv`, com dependências de execução instaladas.
- Banco PostgreSQL local separado: `datumlex_local_core`, no serviço existente em loopback, porta 5433.
- Credenciais em `backend/.env`, ignorado pelo Git, com ACL restrita ao usuário desta máquina e SYSTEM. Não compartilhar esse arquivo. A chave DataJud local foi reutilizada sem exposição; senha de suporte e chave Django foram geradas para esta instalação.
- Tarefa Windows: `DatumLex-Local-5400D7A3`, diariamente às 19h40, no fuso de Brasília configurado no Windows. Tarefa instalada para o usuário conectado, com retomada após horário perdido, sem sobreposição da mesma tarefa e sem interrupção automática na troca para bateria. Não liga o computador, não faz login e não inicia Docker automaticamente.
- Próxima execução agendada após a configuração: 29/10/2026 às 19h40.

## Etapas

1. DataJud TJDFT e STJ são tentados separadamente, desde 2016 até o limite atual do recorte, usando cursores persistidos. Cinco páginas de 100 por tribunal resultam em até 1.000 registros consultados por rodada nesta configuração; isso não garante 1.000 documentos novos. Atualizações, duplicatas, rejeições e falhas da fonte reduzem o incremento. A incremental fica para outra rodada quando o histórico acaba, sem acrescentar outro lote nessa execução.
2. Pangea é consultado por sete temas, com limite por pesquisa. Suas referências são contadas separadamente dos documentos DataJud.
3. A reconciliação de identificadores não aprova relações jurídicas.
4. Havendo TXT STJ arquivados, o NLP é executado e seus resultados são importados idempotentemente como candidatos pendentes. A amostra de avaliação é preparada, sem preencher uma referência humana ou liberar produção.

## Resultado inicial e limites

A primeira tentativa real importou pelo menos 816 referências Pangea únicas. O DataJud não respondeu após as tentativas limitadas e não inseriu documentos nessa etapa. A falha foi registrada; ela não é tratada como coleta concluída. A primeira execução do Agendador terminou inesperadamente antes da última pesquisa Pangea; as condições de bateria foram ajustadas e a última pesquisa foi executada separadamente para conferência. Os registros já gravados foram preservados.

Três textos públicos STJ já arquivados nesta máquina foram copiados para a área de dados ignorada desta instalação, mantendo hashes e metadados. Eles são de 2026. O processamento e a importação local produziram três extrações e 39 citações, ainda sem aprovação jurídica. Não há comprovação de cobertura textual de 2016–2025. O NLP aceita esse período, mas não obtém automaticamente todos os textos históricos. A rotina atual não inclui um coletor histórico completo de inteiro teor STJ/TJDFT.

Foi criado um backup do banco local antes da primeira coleta, em backend/data/backups/. Esse backup inicial não constitui uma política automática diária de backup ou um teste de restauração.

## Acompanhamento

Na raiz do clone:

```powershell
.\scripts\status.ps1
```

Log: `backend/data/datajud-scheduler.log`. Algumas mensagens de bloqueio de alvo remoto nos horários 21:02, 21:03 e 21:10 do dia 28/10 foram geradas por testes de engenharia, não por tentativas de publicar dados na Render. Os testes posteriores passaram a usar um logger isolado.

Para executar manualmente, use `scripts/run-local.ps1` ou inicie a tarefa desta cópia pelo Agendador, evitando executar os dois ao mesmo tempo. Para desativar esta rotina: `Disable-ScheduledTask -TaskName 'DatumLex-Local-5400D7A3'`.

Computador, sessão do usuário, Docker/contêiner e internet precisam estar disponíveis. As tarefas antigas de outras cópias não foram alteradas. Esta rotina não publica na Render. Para outra máquina, siga AUTOMACAO-LOCAL.md; configurações, banco, arquivos de dados e tarefa desta instalação não acompanham o clone.
