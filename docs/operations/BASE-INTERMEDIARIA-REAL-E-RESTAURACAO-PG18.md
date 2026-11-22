# Base Intermediária Pesquisável (Dados Reais Minimizados) e Restauração em PostgreSQL 18

Este documento detalha a preparação técnica de um banco intermediário PostgreSQL local, minimizado e saneado, a partir de `datumlex_ops_f3_full` (`civil-2010-sgt-2026-11`), sem modificar a origem e **sem realizar upload ou publicação remota**.

---

## 1. Mapa de Dependências (14 Tabelas Incluídas vs. 19 Excluídas)

### Tabelas preservadas (mínimo para pesquisa individual, CNJ, filtros, detalhes, mérito e exportações)

| Tabela | Papel funcional | Campos minimizados / saneados |
|---|---|---|
| `accounts_court` | Escopo de tribunais pesquisáveis (9 tribunais com dados) | Apenas catálogo de códigos/nomes de tribunais; zero usuários. |
| `dim_process` | Pesquisa por CNJ exato e contagem de CNJs distintos (`4.516`) | Exigido `secrecy_level = 0` e formato exato de 20 dígitos em 100% das linhas. |
| `dim_time` | Filtro temporal (`dataAjuizamento`, `1.850` datas) | Intacto. |
| `dim_class` | Classe processual no detalhe/exportação (`53` classes) | Intacto. |
| `dim_degree` | Filtro por instância (`G1`, `G2`, `JE`, `TR`, `SUP`) | Intacto. |
| `dim_result` | Classificação de desfecho de mérito (`7` estados) | IDs preservados exatamente como na origem. |
| `dim_org` | Órgão julgador no detalhe/exportação (`1.097` órgãos) | Verificado sem e-mail/CPF. |
| `dim_subject` | Assuntos TPU (`397` assuntos referenciados) | Apenas assuntos referenciados por `fact_process_subject`. |
| `extraction_run` | Metadados de proveniência da coleta (`75` runs referenciados) | `cursor = NULL`, `error = ''`, `scope` filtrado por allowlist (removidos `source_database`, `source_run_ids`, etc.). |
| `warehouse_civilsamplingcohort` | Identidade da coorte `civil-2010-sgt-2026-11` (`1`) | Intacto. |
| `fact_resource` | Documentos DataJud (`4.518`) | **`raw_payload = {}`** (100% removido). |
| `fact_process_subject` | Associação documento × assunto TPU (`8.590`) | Intacto. |
| `warehouse_civilsamplemember` | Vínculo da coorte pesquisável (`4.518`) | Intacto. |
| `process_movement` | Prova mínima dos desfechos mapeados (`584` movimentos) | Apenas códigos em `outcomes.CODES` com data válida; **`complements = []`**, **`name = ''`**. |

### Tabelas estritamente excluídas (`0` registros garantidos por auditoria)
- **Autenticação, sessões e auditoria local:** `accounts_user`, `accounts_user_courts`, `accounts_supportidentity`, `accounts_auditevent`, `accounts_requestlimit`, `django_session`.
- **Acervo jurídico sem autorização de publicação remota:** `legal_reference`, `warehouse_legalcorpusitem`, `warehouse_legalcorpustopicmatch`, `warehouse_legalnarrativedraft`, `warehouse_crosssourcelinkcandidate`.
- **Histórico NLP e rejeições:** `warehouse_nlpsnapshot`, `warehouse_nlpdocument`, `warehouse_nlptextversion`, `warehouse_nlpextraction`, `warehouse_nlpevidence`, `warehouse_nlprevision`, `warehouse_nlpsourceobservation`, `rejected_record`.

---

## 2. Revisão de Sigilo e Governança (Não Presumir Redistribuição Automática)

- **Achados técnicos verificados em `datumlex_ops_f3_full`:**
  - `100%` dos `4.516` processos possuem `secrecy_level = 0` e formato CNJ de 20 dígitos válido (`0` processos sigilosos).
  - `100%` dos `4.518` registros de `fact_resource` têm `raw_payload = {}` (sem nomes de partes, advogados, documentos pessoais ou textos livres).
  - `100%` dos `584` registros de `process_movement` têm `complements = []` e `name = ''`, mantendo apenas código numérico TPU, data e fingerprint SHA-256 necessários ao `classify()` dos `269` resultados elegíveis.
- **Ressalva jurídica obrigatória:** a origem na API pública do DataJud/CNJ **não equivale automaticamente** a autorização de redistribuição pública irrestrita de números de CNJ individuais em ambiente hospedado na internet. Por isso, o banco intermediário e seu export `.dump` permanecem **estritamente privados e locais** (fora do Git, permissões `0700`/`0600`) até decisão/autorização formal.

---

## 3. Procedimento Técnico de Restauração em PostgreSQL 18 (Somente se Autorizado)

> **Importante:** nenhuma transferência para o Railway foi executada. O procedimento abaixo pressupõe autorização explícita prévia.

### 3.1 Pré-requisitos e Backup do Destino Atual
1. Confirmar integridade do export privado antes de qualquer ação:
   ```sh
   shasum -a 256 recuperacao/staging_real_deploy/datumlex_staging_real_civil_2026_11.dump
   ```
   *(Comparar com o campo `dump_sha256` em `datumlex_staging_real_civil_2026_11.manifest.json`.)*
2. Se o ambiente de destino já possuir banco anterior, fazer backup lógico do destino antes de alternar a conexão (`pg_dump -Fc --no-owner --no-privileges`).

### 3.2 Criação de Banco PG 18 Limpo e Restauração (Usando Cliente `pg_restore` 18)
1. Criar um **banco novo e vazio** no PostgreSQL 18 (obrigatório para evitar conflito com triggers `nlp_no_truncate` / `support_immutable` em restaurações `--clean`):
   ```sql
   CREATE DATABASE datumlex_demo_real_pg18
     WITH ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0;
   ```
2. Restaurar o export minimizado em transação única (usando `pg_restore` **versão 18**):
   ```sh
   pg_restore --no-owner --no-privileges --single-transaction --exit-on-error \
     --dbname="$TARGET_PG18_URL" \
     recuperacao/staging_real_deploy/datumlex_staging_real_civil_2026_11.dump
   ```
   *(O dump já contém as 36 migrações Django aplicadas, os 16 triggers, as 3 funções PL/pgSQL e apenas as 14 tabelas procedurais saneadas.)*

### 3.3 Conferência de Migrações, Integridade e Saneamento Pós-Restauração
1. Verificar migrações sem aplicar alterações inesperadas:
   ```sh
   python manage.py migrate --check
   ```
2. Executar auditoria somente leitura no destino:
   ```sh
   STAGING_TARGET_DATABASE_URL="$TARGET_PG18_URL" \
     python manage.py prepare_real_staging --audit-only
   ```
   Confirmar:
   - `total_documents == 4518`, `total_distinct_cnjs == 4516`, `merit_binary.eligible == 269` (`granted == 25`, `denied == 244`).
   - `all_excluded_tables_zero == true`, `secrecy_level_zero_only == true`, `raw_payload_minimized == true`, `movements_minimized == true`, `extraction_runs_minimized == true`.
   - `canonical_sha256` idêntico ao manifesto local.
3. Provisionar **exclusivamente** contas de acesso destinadas ao ambiente de demonstração (nunca reutilizar senhas locais) e configurar `RESEARCH_CIVIL_COHORT=civil-2010-sgt-2026-11`, `DATUMLEX_SYNTHETIC_PREVIEW=false`, `RESEARCH_GEMINI_ENABLED=false` e `DATUMLEX_PUBLIC_REGISTRATION_COURTS` conforme política definida para o ambiente.

### 3.4 Rollback Seguro
1. Como a origem local `datumlex_ops_f3_full` nunca é modificada e o restore ocorre em um novo banco PG 18, qualquer falha é revertida apontando `DATABASE_URL` de volta ao banco anterior (ou mantendo a demonstração local).
2. Descartar o banco PG 18 recém-criado (`DROP DATABASE datumlex_demo_real_pg18;`) se qualquer verificação de integridade ou governança falhar.
