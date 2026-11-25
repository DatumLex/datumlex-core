# Liberação Local Auditável de Metadados — Jurisprudência e Doutrina

Procedimento opcional e fail-closed para autorizar **exclusivamente exibição local de metadados e links oficiais (`display`)** no banco operacional `datumlex_ops_f3_full`.

> **Atenção:** nenhuma fonte real foi aprovada automaticamente. Os dois acórdãos de erro médico (`TJDFT:ACORDAO:1218333` e `STJ:RESP:1145728:MG`) estão **fora** da lista permitida deste procedimento por exigirem revisão reforçada de dados sensíveis.

## Fontes candidatas suportadas individualmente

1. **Jurisprudência:** `TJDFT:ACORDAO:1955493` (atualiza apenas `LegalCorpusItem`)
2. **Doutrina:** `SENADO:RIL:61:241:237` (atualiza atomicamente `LegalReference` e `LegalCorpusItem`; finalidade restrita a referência bibliográfica e link externo, sem texto integral, NLP ou Gemini)

O responsável humano pode autorizar **somente uma**, **ambas** ou **nenhuma**.

## Formato do arquivo de decisão humana (`decisao_4g.json`, privado fora do Git)

```json
{
  "schema_version": 1,
  "environment": "local:datumlex_ops_f3_full",
  "purpose": "display",
  "decisions": {
    "TJDFT:ACORDAO:1955493": {
      "decision": "allow",
      "permission": "display",
      "reviewer": "Pedro Mattos",
      "role": "responsável pelo produto",
      "approval_reference": "DATUMLEX-4G:TJDFT:ACORDAO:1955493",
      "decided_at": "2026-11-22T20:00:00-03:00",
      "scope": "local:datumlex_ops_f3_full",
      "deliverable": "metadados e link oficial no portal do TJDFT, sem texto integral",
      "expected_fingerprint": "1398af2191aac16d0d3c838afc1f6252860e59d9ed0da1dcb2958fc7e2e2d585"
    }
  }
}
```

Para incluir a doutrina `SENADO:RIL:61:241:237`, adicionar sua entrada individual em `decisions` com `expected_fingerprint: "15b8358a2f086c86628de367f294c76ab1c479435fa78d6d81bb2a4cfb5e626f"` e `approval_reference: "DATUMLEX-4G:SENADO:RIL:61:241:237"`.

## Comandos (executados no `backend/` oficial conectado exclusivamente a `datumlex_ops_f3_full`)

### 1. Diagnóstico somente leitura (`--check`)
```sh
../../recuperacao/runtime/bin/python manage.py manage_legal_display_approval --check
```

### 2. Simulação sem gravar (`--dry-run`)
```sh
../../recuperacao/runtime/bin/python manage.py manage_legal_display_approval \
  --dry-run \
  --ids TJDFT:ACORDAO:1955493 \
  --decision-file ../../recuperacao/decisao_4g.json
```

### 3. Aplicação real (somente após decisão humana explícita)
```sh
../../recuperacao/runtime/bin/python manage.py manage_legal_display_approval \
  --apply \
  --ids TJDFT:ACORDAO:1955493 \
  --decision-file ../../recuperacao/decisao_4g.json \
  --snapshot ../../recuperacao/DATUMLEX_4G_ESTADO_ANTERIOR.json \
  --receipt ../../recuperacao/DATUMLEX_4G_LIBERACAO.json
```

### 4. Revogação individual (simulação ou real)
```sh
# Simulação sem gravar:
../../recuperacao/runtime/bin/python manage.py manage_legal_display_approval \
  --dry-run --simulate-revoke \
  --ids TJDFT:ACORDAO:1955493 \
  --snapshot ../../recuperacao/DATUMLEX_4G_ESTADO_ANTERIOR.json \
  --receipt ../../recuperacao/DATUMLEX_4G_LIBERACAO.json

# Revogação efetiva:
../../recuperacao/runtime/bin/python manage.py manage_legal_display_approval \
  --revoke \
  --ids TJDFT:ACORDAO:1955493 \
  --snapshot ../../recuperacao/DATUMLEX_4G_ESTADO_ANTERIOR.json \
  --receipt ../../recuperacao/DATUMLEX_4G_LIBERACAO.json
```

## Garantias de bloqueio
- Rejeita execução se `SYNTHETIC_PREVIEW=true`, se variáveis de ambiente Railway/Vercel/Render estiverem presentes, ou se o banco não for `datumlex_ops_f3_full` em loopback local.
- Rejeita qualquer identificador fora das duas candidatas permitidas.
- Rejeita qualquer finalidade diferente de `display` ou ausência de decisão humana individual.
- Nunca libera `text`, `nlp` nem `gemini`.
- Mantém snapshot prévio (`0600`, sem sobrescrita) e valida revogação individual em savepoint antes de confirmar a transação.
