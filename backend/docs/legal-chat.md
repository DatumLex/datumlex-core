# Chat de análise jurídica com Gemini — v1

Implementação local de apoio à pesquisa (#133/#135). Não constitui aceite integral da história, revisão independente ou aconselhamento jurídico.

## Ativação

No arquivo local `backend/.env` (não versionado), configure:

```dotenv
GEMINI_API_KEY=sua_chave_local
GEMINI_MODEL=gemini-2.5-flash
```

Confira a disponibilidade e as cotas do modelo no Google AI Studio. A existência de uma chave não garante gratuidade. Não use variáveis `VITE_*` para segredos e não cole a chave em commits, logs ou no chat.

Aplique a migração e inicie os serviços pelos comandos habituais do projeto:

```powershell
cd backend
.venv/Scripts/python.exe manage.py migrate
```

Na consulta, abra **Chat de análise · IA**. O painel salva um snapshot canônico com os tribunais, assunto e período aplicados. Somente trechos com revisão e liberação de qualidade entram na geração. Se nenhuma fonte estiver liberada, o sistema bloqueia a geração, sem fabricar resultados. Configurar a chave não libera evidências automaticamente.

## Fluxo e contratos

- `POST /api/v2/analysis-snapshots/{id}/chat/`: pergunta (3–2000 caracteres), `consent: true`, `parent_id` opcional para encadear versões.
- `GET /api/v2/legal-drafts/{id}/`: recupera a versão; exige propriedade, acesso ao snapshot e manutenção da liberação de fontes.
- `POST /api/v2/legal-drafts/{id}/`: aprovação explícita com `expected_sha256`, `conclusions` (até 10000 caracteres) e `confirmed: true`.
- `GET /api/v2/legal-drafts/{id}/export/`: JSON UTF-8, disponível somente após aprovação.

Contrato `legal-narrative/1.0`; prompt `grounded-legal-pt/1.0`; recuperação `snapshot-lexical/1.0`; modelo persistido `LegalNarrativeDraft`, migração `0015_legalnarrativedraft`.

O backend envia somente contexto salvo, pergunta e até 20 evidências (orçamento de 50000 caracteres serializados), ordenadas por sobreposição lexical e identificador estável. Não usa pesquisa web nem respostas anteriores como evidência. Não envia a chave ao navegador. O usuário autoriza o envio ao Google na interface. No Free Tier, conteúdo pode ser usado para melhoria dos produtos Google; não envie conteúdo sigiloso.

Cada versão mantém contexto e hash do snapshot, IDs/revisões/versões e hashes dos textos, citações, interpretações, incertezas, modelo, contrato, prompt, uso de tokens e latência. Custo não é estimado: a interface orienta consultar a conta Google.

Os fatos exibidos são citações literais verificadas. Interpretações precisam apontar evidências existentes. Citação inexistente, ausência de evidência, resposta truncada ou status `insufficient`/`conflicting` bloqueiam a geração. Trechos e perguntas são tratados como dados não confiáveis no prompt. Textos são renderizados como texto React, sem HTML do modelo.

O rascunho técnico é persistido para rastreabilidade. Não se torna uma análise final exportável antes da aprovação humana. A saída do modelo é preservada; correções e conclusões do usuário ficam em seção própria. Regenerar cria uma versão com vínculo à anterior. A versão aprovada não pode ser editada por esse endpoint.

## Validação executada

```powershell
backend/.venv/Scripts/python.exe backend/manage.py test tests.test_legal_chat tests.test_nlp_dashboard --noinput
cd frontend
npm.cmd run build
npm.cmd run lint
# Com Vite em http://127.0.0.1:5182:
node tests/legal-chat.mjs
```

Resultado local (13/11/2026): 34 testes passaram; build e lint passaram; teste de navegador passou. Migração 0015 aplicada ao PostgreSQL local. Nenhuma chamada real ao Gemini foi realizada.

Testes usam fontes sintéticas e Gemini simulado; não consomem a chave real nem validam qualidade jurídica. Cobrem contexto/versão, revisão/aprovação/exportação, UTF-8, ausência de evidência, citações inventadas, status conflitante/insuficiente, acesso revogado, cotas locais e contrato HTTP com o provedor.

## Limites e pendências para aceite da história

- Verificação automática confirma IDs e correspondência literal. Não demonstra suporte semântico de uma interpretação nem detecta todas as contradições. Requer avaliação de citações e revisão humana com fontes reais.
- Recuperação lexical limitada pode omitir passagens relevantes; o corpus é parcial. Não produz probabilidades de vitória.
- Integração PDF existente abre as evidências do mesmo snapshot, mas não incorpora a narrativa aprovada. A exportação da narrativa v1 é JSON.
- Não há teste real do Gemini sem chave/configuração. Não há implantação, revisão independente ou aceite do Product Owner nesta entrega.
- O histórico persiste no backend e pode ser recuperado por ID; a conversa da interface é mantida durante a sessão do painel. Não há listagem de conversas antigas.
- Aplica-se a validade e a revogação do snapshot existente (24h por padrão); versões não continuam exportáveis quando seu acesso expira.
- Limite local: uma geração por minuto por usuário, via cache Django. Produção com múltiplos processos precisa de cache compartilhado e limites globais no provedor.
- Requisições têm timeout de 45s no provedor e 60s no navegador. Não há retentativa automática, streaming ou garantia de idempotência após queda de conexão.

Referências: https://ai.google.dev/api/generate-content e https://ai.google.dev/gemini-api/docs/pricing.
