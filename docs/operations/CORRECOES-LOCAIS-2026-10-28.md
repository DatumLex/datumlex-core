# Correções locais de 28/10/2026

Projeto de destino: `C:/API/datumlex-core`. Nenhum comando Git, commit, push, coleta externa, publicação na Render ou alteração de tarefa Windows foi executado. Os bancos reais e as credenciais não foram copiados nem modificados. Não foram removidos arquivos preexistentes do projeto.

## Correções aplicadas

- Unificação do calendário de consultas em São Paulo e do suporte desde 2016. A interface permite consultar datas sem registros carregados, sem confundir cobertura da base com limite do filtro.
- Recuperação correta do estado de extração quando a inicialização do cliente DataJud falha.
- Atualização incremental compara assuntos antes de retomar, verifica execução ativa e usa o início da execução anterior como marco de sobreposição.
- Tempo limite PostgreSQL passa a respeitar connect_timeout da URL.
- Reimportação Pangea idêntica preserva aprovação, referência de aprovação, publicação e assunto revisados; conteúdo alterado continua exigindo revisão.
- Contrato de exclusões NLP completo mesmo com seleção vazia.
- Segmentação de quebras HTML STJ com índices originais preservados. Regras e pipeline atualizados para 0.2.1, preservando as melhorias anteriores de citações numeradas e seleção por sentença.
- Recursos de PDF, consulta de fontes e interface já existentes nesta cópia preservados. Testes do PDF histórico passaram.
- Padrão histórico de coleta e agendamento atualizado para 2016, sem reescrever cursores existentes.

## Automação e validação portáteis

Scripts de instalação, execução e agendamento estão em scripts/. Eles resolvem a raiz do clone, sem depender das pastas desta máquina. Instalação de tarefa não começa a coleta imediatamente, exceto com -RunNow. Cada clone recebe nome de tarefa derivado da própria pasta.

O agendador usa o intérprete que o executa e exige alvo local: SQLite ou PostgreSQL em loopback. Não se transforma em publicador remoto por receber uma DATABASE_URL remota. O Compose exige POSTGRES_PASSWORD em vez de fixar uma senha no código; essa alteração não modifica a senha de volumes existentes.

As ferramentas de amostragem, revisão e avaliação NLP estão em tools/nlp_validation/. Os dados ficam em backend/data/operations/, ignorado pelo Git. Nenhum texto judicial, revisão humana ou segredo da outra instalação foi incluído. Há suporte a diagnóstico com um revisor e avaliação independente com revisões e adjudicação. A liberação permanece bloqueada sem corpus, critérios aprovados e qualidade demonstrada.

Veja [Automação local](AUTOMACAO-LOCAL.md) e [Validação NLP](../../tools/nlp_validation/README.md).

## Verificação executada

- Backend: 144 testes executados em SQLite em memória; 140 passaram e quatro foram ignorados por condições do ambiente. Sem problemas no system check. Verificação de modelos não detectou migrações novas necessárias.
- Ferramenta de validação: 11 testes de engenharia passaram, usando textos sintéticos temporários.
- Frontend: ESLint da árvore src passou e build Vite passou, com resultado fora do projeto em pasta temporária.
- Scripts PowerShell: parser não apontou erros de sintaxe. Scripts Python adicionais também passaram na verificação sintática.
- Não foram executados pip install, npm ci, criação de tarefa Windows ou instalação completa do clone. Os testes usaram runtimes/dependências já disponíveis na máquina, com versões que podem diferir dos arquivos de requisitos. Uma junção temporária para as dependências frontend foi removida depois dos testes. Para executar esta cópia normalmente, siga setup.ps1 e configure suas dependências e backend/.env.
- As configurações aceleradas de hash de senha foram limitadas aos processos de teste; a configuração da aplicação não foi alterada para MD5.

## Backup e limites

Backup dos arquivos próprios preexistentes, excluindo .git, dependências, dados e .env: `D:/Api/datumlex-operations/private/c-api-core-before-corrections-20261028-205809.zip`.

Não se afirma cobertura documental completa de 2016–2026 nem aprovação jurídica do NLP. A integração de publicação local→Render não foi implementada nesta alteração. O teste de instalação em máquina limpa e a jornada autenticada visual desta cópia ainda não foram executados.
