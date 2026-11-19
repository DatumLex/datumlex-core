# Render deployment

`render.yaml` provisions three resources for the college-project deployment:

- `datumlex-web-pedromattos`: Vite static frontend;
- `datumlex-api-pedromattos`: Django web service;
- `datumlex-db-pedromattos`: PostgreSQL 17 database.

## Required secrets

### Pesquisa e chat integrados

O React abre a pesquisa após o login. O Django atende `/api/research/`, `/api/research/sources/`,
`/api/research/chat/` e `/api/research/export/` no serviço de API existente. O chat padrão consulta o banco
e as ementas sem acessar a OpenAI. Os indicadores são calculados no servidor em ambos os modos.

Para testar o React local com um backend já atualizado no Render, use `VITE_API_BASE_URL=/api` e
`DATUMLEX_DEV_API_TARGET` em `frontend/.env.local`, com a origem HTTPS pública exibida pelo serviço Django.
Reinicie o Vite. O destino padrão do proxy é `http://127.0.0.1:8000`. Para testes de login pelo proxy,
autorize a origem local exata em `CSRF_TRUSTED_ORIGINS` no ambiente de teste do Django. A conexão com o
PostgreSQL permanece em `DATABASE_URL` no backend.

No workspace que já usa `datumlex-demo-api`, `datumlex-demo-web` e `datumlex-demo-db`, publique a
mesma revisão do repositório na API e no site já existentes, atualizando primeiro a API. O Blueprint
abaixo usa outros nomes de recursos. Confirme `/api/health/`, faça login e confira os filtros de TJDFT + STJ,
uma fonte de doutrina, um precedente, uma pergunta com citação e a exportação do recorte.

O modo generativo é opcional. Depois de verificar o saldo e o faturamento da organização de API,
configure `OPENAI_API_KEY` como segredo do backend, `RESEARCH_OPENAI_MODEL` como modelo autorizado
e `RESEARCH_OPENAI_ENABLED=true`. Nesse modo uma pergunta envia a pergunta, o contexto recente,
os indicadores e trechos selecionados à OpenAI. O carregamento do painel continua usando a síntese local.
Se a API externa estiver indisponível, a interface identifica a resposta de consulta direta ao banco.

### Credenciais do Blueprint

The Render Blueprint prompts for two values. Do not commit either value:

- `DATUMLEX_SUPPORT_PASSWORD`: the initial immutable `suport` account password;
- `DATAJUD_API_KEY`: the current public key published by CNJ, without the `APIKey ` prefix.

The Blueprint generates `DJANGO_SECRET_KEY` and injects the database connection automatically.

## Initial data

Free web services apply migrations and provision support in the build command.
Provisioning does not reset an existing support password. Migrations may change the
database even if a later deployment step fails; use compatible migrations and backups.
Data extraction is deliberately separate from application startup: restarting or
deploying the API must not start an unlimited collection or reclaim a running extractor.

Migrations create an empty database. After the first deploy, either restore a compatible
PostgreSQL dump or run the bounded DataJud extractor from the backend service. The local
development database is intentionally ignored by Git and is never included in a deploy.

## Historical data and PDF summaries

DataJud extraction and dashboard filters accept filing dates from **2016-01-01** through
today. The current year is incomplete. A date range does not establish complete court
coverage. Existing saved runs keep their original scopes and cursors.

For a bounded collection, run from `backend/` with the intended database configured:

```powershell
.venv/Scripts/python.exe manage.py extract_datajud --court TJDFT --start 2016-01-01 --subjects 10431,10433,10439 --page-size 100 --max-pages 1
# Repeat for --court STJ. Continue using the printed --resume ID.
```

The dashboard's **Exportar resumo em PDF** button downloads an authenticated report of
the applied court, subject and period selection. The PDF includes DataJud document counts,
distinct CNJ numbers, binary rates and denominator, exclusions, annual volume, collection
time and limitations. It queries a consistent database snapshot at export time; later
collection can make it differ from a dashboard loaded earlier. It does not merge Pangea
references or unreviewed NLP evidence into the DataJud metrics. The existing NLP snapshot
report remains available separately for reviewed textual evidence.

When STJ is selected, the PDF also includes a separate Pangea inventory summary and
up to five source-linked thesis excerpts with review status and cited process identifiers. Unknown publication dates
are disclosed and excluded from temporal counts; source update dates are never used as
judgment dates. Unclassified TPU subjects are explicitly labeled as contextual material,
without asserting that they match the selected subject. References with a known publication
date outside the requested period are omitted from the excerpt sample. Pangea entries do
not change the DataJud denominator or rates.

`GET /api/report.pdf/` uses the same query validation and court permissions as statistics.
Reports are marked `no-store`; no judicial record, user account or password is modified.

The five-page PDF follows the supplied Sprint 2 research report layout: overview,
results and annual trend, precedents/theses, traceability, and source limitations.
Illustrative values from the reference are never reused. Annual rates use filtered
DataJud binary outcomes; missing denominators leave gaps in the chart. Reviewed
adherence uses eligible human assessments by decision date, explicitly separate from
filing-date DataJud volumes. NLP frequency and coverage remain unavailable here until
a reviewed evidence snapshot is integrated; the separate NLP evidence report remains available.

## Limitations of the free configuration

The Blueprint uses free plans for an initial academic demonstration. Render's free PostgreSQL
database expires after 30 days, has no backups, and must not be treated as durable production
storage. Upgrade the database before relying on it for a long-lived public deployment.

## Custom domains

For a custom domain, use sibling hosts such as `app.example.com` and `api.example.com`, then
update `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, and the frontend's
`VITE_API_BASE_URL`. Rebuild the frontend after changing its API URL.
