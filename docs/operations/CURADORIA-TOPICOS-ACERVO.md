# Curadoria de Metadados e Tópicos Editoriais do Acervo Jurídico

Documento técnico de apoio à revisão humana do acervo jurídico (sem aprovação automática nem alteração de dados reais).

## Caso investigado: `SENADO:RIL:57:226:71` (`responsabilidade-civil`)

### Diagnóstico no código
1. O catálogo temático léxico em `backend/src/nlp/topics.py` define **10 subtemas específicos** (`dano-moral`, `dano-material`, `saude`, `transito`, `negativacao`, `transporte-aereo`, `imovel`, `imagem`, `perda-chance`, `internet`). O código geral `responsabilidade-civil` não pertence a essa lista.
2. Na carga da Fase 3B (`stage_legal_collection.py`), os vínculos em `LegalCorpusTopicMatch` são criados apenas para a interseção `set(row["topics"]) & TOPIC_IDS`. Como o artigo `SENADO:RIL:57:226:71` possui apenas `["responsabilidade-civil"]`, foram criados **0 registros** em `LegalCorpusTopicMatch`.
3. Anteriormente, `scoped_items()` em `backend/src/services/corpus_catalog.py` aplicava `topic_matches__isnull=False` mesmo quando nenhum filtro de tema específico estava ativo — o que tornava invisível qualquer fonte aprovada de escopo geral sem subtema específico.

### Correção segura aplicada na camada de consulta e apresentação
- `scoped_items()` mantém integralmente o bloqueio fail-closed de `published_items(use)` (`review_status="approved"`, `permissions__display="allowed"` e `LegalReference.approved=True` quando vinculada), mas **não exige `topic_matches__isnull=False`** quando o usuário consulta *"Todos os temas"*.
- Quando o usuário filtra por um subtema específico (ex.: `dano-material`, `transito`, `saude`) ou marca `complete_only=true`, o filtro por `LegalCorpusTopicMatch` continua exigindo vínculo explícito — **nenhum subtema é atribuído automaticamente sem respaldo editorial**.
- Na apresentação (`source_metadata.py`), o rótulo `responsabilidade-civil` é exibido como **`Responsabilidade civil (escopo geral)`** nas fichas aprovadas, preservando a distinção em relação aos 10 subtemas filtráveis.

### Decisão editorial pendente para o responsável pelo produto
Ao aprovar `SENADO:RIL:57:226:71` localmente para `display`, o responsável humano pode optar por:
- **Opção A (padrão sem novos vínculos):** manter o artigo no escopo geral `responsabilidade-civil` — após receber grant `display`, ele já aparecerá normalmente em *"Todos os temas"* na Pesquisa, no Acervo por assunto e nas exportações, sem aparecer sob subtemas específicos.
- **Opção B (se houver aceite editorial explícito):** vincular também o subtema `dano-material` (*Dano material e reparação integral*) em `LegalCorpusTopicMatch` no momento da aprovação, caso deseje que o artigo também apareça ao filtrar por esse tema específico.
