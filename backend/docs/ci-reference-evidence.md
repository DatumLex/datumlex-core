# CI de referências e evidências NLP

O workflow `.github/workflows/reference-nlp-ci.yml` roda em PRs para `main`,
em pushes na `main` e manualmente. Cada check usa PostgreSQL 17 descartável,
Python 3.13, dependências fixadas e dados sintéticos. Não requer chaves de APIs,
arquivos reais, acesso ao banco principal ou coleta DataJud.

## Checks estáveis para a proteção da main

- `Test 1 - Reference idempotency`: importa precedentes e doutrina duas vezes,
  verifica contagens e categorias; testa cache para evitar novo cálculo NLP da
  mesma versão e regras. Mudanças no texto ou regras invalidam o cache.
- `Test 3 - NLP evidence integrity`: confere trechos e posições Unicode, hash,
  identidade documental e separação entre versões; verifica rejeição sem
  gravações parciais, histórico imutável e concorrência de revisões no PostgreSQL.

Os dois checks também verificam configuração Django, migrações esquecidas e
aplicação das migrações num banco vazio. O runner limpa os serviços ao terminar.
Os testes não comprovam interpretação jurídica nem completude do acervo.

## Ativação no GitHub

1. Publicar a branch e abrir PR para a `main`.
2. Esperar os dois checks aparecerem e passarem no PR.
3. Em Settings > Rules > Rulesets (ou proteção de branches), editar a regra da
   `main`, exigir PR e revisão da equipe e selecionar os dois checks acima como
   obrigatórios. Essa regra é configuração do repositório, não do arquivo YAML.
4. Conferir a regra antes do merge. Não configurar bypass para contornar falhas.

## Reprodução local

Usar ambiente virtual com `backend/requirements.txt` e definir `DATABASE_URL`
para um PostgreSQL exclusivo de testes. O usuário precisa criar o banco Django
`test_...`. Nunca apontar para credenciais ou banco principal para validar o CI.

Na pasta `backend`:

```text
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --noinput
python manage.py test tests.test_reference_nlp tests.test_nlp_computation_cache --noinput --verbosity 2
python manage.py test tests.test_nlp_evidence tests.test_ci_evidence_integrity --noinput --verbosity 2
```

Documentação: https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers
