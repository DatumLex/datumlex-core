# Automação local a partir de um clone

Todos os comandos abaixo partem da raiz do projeto. Os scripts resolvem a pasta do clone, sem depender de C:/API ou D:/Api. Credenciais e dados não acompanham o código.

## Instalação

Instale Python compatível com as dependências, Node.js/npm e, para PostgreSQL, Docker Desktop. O setup instala dependências pela rede quando executado; nenhuma instalação nem coleta externa foi executada durante a preparação destas correções.

```powershell
.\scripts\setup.ps1
```

Preencha `backend/.env`, criado a partir de `.env.example`, com a chave DataJud e as configurações da sua máquina. Para usar PostgreSQL, escolha POSTGRES_PASSWORD e use a mesma senha, codificada para URL quando necessário, em DATABASE_URL apontando para 127.0.0.1:5433. Configure também a senha de suporte exigida para o primeiro provisionamento. Não copie credenciais de outra pessoa.

```powershell
docker compose --project-directory backend -f backend/compose.yaml up -d
.\scripts\setup.ps1 -Migrate -SkipDependencies
```

Se preferir SQLite, deixe DATABASE_URL vazio e dispense o Compose. O Compose agora exige POSTGRES_PASSWORD; mudar essa variável não altera a senha de um volume PostgreSQL já existente. Preserve volumes existentes e confira suas credenciais antes de reutilizá-los. A migração é uma etapa explícita de instalação; a coleta diária não recria bancos.

## Execução e agendamento

```powershell
# Um lote DataJud/Pangea e reconciliação técnica de citações.
.\scripts\run-local.ps1

# Instalar rotina diária, sem começar uma coleta imediatamente.
.\scripts\install-schedule.ps1 -At '19:40'

# Opcional: instalar e também começar agora.
.\scripts\install-schedule.ps1 -At '19:40' -RunNow

# Ver estado da tarefa desta cópia e últimas linhas do log.
.\scripts\status.ps1
```

A tarefa recebe um nome derivado da pasta do clone, evitando sobrescrever a tarefa de outra cópia. Usa o horário configurado no Windows, requer sessão de usuário e computador disponível, evita sobreposição da mesma tarefa e grava logs em backend/data/datajud-scheduler.log. Não foi criada ou alterada uma tarefa Windows nesta entrega.

A coleta é limitada por execução e retoma os cursores dos recortes correspondentes. O histórico solicitado começa em 2016, mas isso não comprova cobertura integral da fonte. Cursores antigos mantêm seu escopo original. Uma cópia separada apontando para o mesmo banco pode disputar o trabalho: a configuração IgnoreNew protege a mesma tarefa, não todos os processos possíveis.

O lote padrão DataJud consulta até cinco páginas de 100 registros por tribunal, até 1.000 registros na soma TJDFT/STJ. Registros atualizados, repetidos ou rejeitados podem fazer o total de documentos novos ficar abaixo de 1.000. Pangea e evidências NLP são contados separadamente. Esse limite pressupõe os cursores criados por esta configuração de 100 registros por página; cursores antigos com outro page_size preservam o tamanho original. Ao concluir o histórico, a atualização incremental começa na execução seguinte, evitando somar um segundo lote na mesma rodada.

O agendador exige banco local ou SQLite. Não use esse comando para publicar diretamente na Render. A rotina agenda metadados DataJud/Pangea e reconciliação. Quando há textos STJ em backend/data/operations/stj-documents/texts, também processa o NLP, importa resultados idempotentes como pendentes de revisão e prepara a amostra de avaliação. Sem textos, registra a pendência, sem fabricar resultados. Obtenção de inteiro teor, revisão humana e publicação são etapas distintas. Confira [as ferramentas de validação NLP](../../tools/nlp_validation/README.md).

## Publicação e limites

Não foi incorporado um publicador remoto completo nesta alteração. Uma publicação futura precisa transferir dados e textos com validação, backup e preservação de contas. Clonar o projeto não dá acesso à Render nem ao banco de outra pessoa.

Não há corpus real embutido na entrega. Os comandos de preparação NLP precisam da fila e dos textos locais verificáveis. Nenhuma métrica jurídica é aprovada sem a referência humana necessária.
