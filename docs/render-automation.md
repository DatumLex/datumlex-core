# Configuração de extração no servidor

A tela **Automação**, disponível ao perfil Master, salva uma configuração por
instalação no PostgreSQL. Não usa arquivos do computador do cliente nem o disco
efêmero do serviço web. A migração `warehouse.0016` cria a tabela com a automação
pausada. GET/PUT/POST usam a sessão e o CSRF existentes. Não há endpoint público
para iniciar processos nem segredos na resposta.

## Fluxo do cliente

1. Selecionar fontes, tribunais, temas, período e horário de Brasília.
2. Salvar. Isso não ativa o agendamento nem inicia coleta.
3. Quando o executor estiver conectado, ativar ou solicitar uma coleta.
4. Acompanhar a última rodada e atualizar o status. Pausar cancela a fila e os
   próximos agendamentos; uma rodada que já começou pode terminar.

DataJud fornece metadados processuais e movimentos. Pangea fornece precedentes e
teses. Os coletores de jurisprudência textual STJ e doutrina Senado/STJ não estão
integrados a esta rodada: aparecem identificados e desabilitados na tela.
A meta de 300 documentos por trimestre soma os tribunais selecionados, com filtro
de assuntos CNJ e prioridade aos recortes menos representados. Não é garantia
de cobertura. Cada rodada tem orçamento de páginas; fontes indisponíveis são
reportadas. Não há aprovação automática de evidências nem preenchimento fictício.

## Executor separado da aplicação web

O comando abaixo verifica a fila e executa no máximo uma rodada:

```sh
python manage.py run_server_automation
```

Ele deve ser executado por um agendador externo ao Gunicorn, a cada 15 minutos
(`*/15 * * * *`, em UTC). O horário escolhido no painel é interpretado em
`America/Sao_Paulo`; a rodada começa na primeira verificação após esse horário.
Não há execução retroativa de todos os dias perdidos.

Configure no executor a mesma revisão do código, as dependências de
`backend/requirements.txt`, `DATABASE_URL`, `DJANGO_SECRET_KEY`,
`AUTOMATION_EXECUTOR_ENABLED=true` e, se usada, `DATAJUD_API_KEY`. O serviço web
também precisa de `AUTOMATION_EXECUTOR_ENABLED=true` para liberar os controles.
O primeiro tick, ainda pausado, registra uma conexão do executor no banco.
A interface só permite ativação se essa conexão tiver menos de 45 minutos.
Desativar a variável em ambos os serviços interrompe novas execuções.

Em Render, use a conexão **interna** com o PostgreSQL do mesmo workspace e região.
Um Cron Job separado pode executar o comando. Este PR NÃO cria esse recurso,
NÃO altera o Blueprint existente e NÃO contrata plano pago: cron no Render é
cobrado separadamente. A publicação da tela mantém a configuração salva e pausada
até o responsável aprovar e configurar um executor. Não há garantia de cron
gratuito dentro de um Web Service gratuito que pode ficar inativo.

## Segurança e limites

- Um advisory lock PostgreSQL impede dois executores simultâneos, inclusive
  disparos manuais concorrentes. SQLite serve aos testes, não ao executor real.
- A fila é consumida sob transação, com snapshot da configuração no status.
  O executor revalida a conta e os tribunais antes das requisições às fontes.
- Um processo interrompido é identificado quando a próxima instância obtém o
  lock. Uma rodada interrompida não é automaticamente repetida no mesmo dia;
  o responsável pode solicitar nova coleta.
- O orçamento preventivo padrão é 850.000.000 bytes de tamanho lógico do banco,
  verificado antes de coletar. Pode ser ajustado pelo responsável via
  `AUTOMATION_DATABASE_BUDGET_BYTES`. Não é uma quota rígida: índices, WAL e uma
  página recém-importada podem aumentar o espaço físico além dessa medida.
- Nenhum dado existente é excluído. Falhas mostram apenas o tipo de erro;
  URLs de conexão, chaves e mensagens potencialmente sensíveis não são retornadas.
- O PR não migra dados existentes nem aplica migrações ao banco de produção.

## Validação local

```sh
python manage.py makemigrations --check --dry-run
python manage.py test tests.test_server_automation --noinput
```

Os testes não chamam as fontes reais nem iniciam agendamentos. A interface deve
mostrar salvamento disponível, fontes pendentes desabilitadas e ativação bloqueada
quando o executor estiver desconectado.
