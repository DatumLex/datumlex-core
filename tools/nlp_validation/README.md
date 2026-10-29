# Validação NLP portátil

Estas ferramentas fazem parte do projeto e usam caminhos relativos à raiz do clone. Não contêm textos judiciais, credenciais, banco nem avaliações humanas de outra instalação.

O diretório de trabalho é `backend/data/operations/`, ignorado pelo Git. Coloque os textos STJ em `backend/data/operations/stj-documents/texts/` e os metadados correspondentes em arquivos `metadata-*.json` no diretório stj-documents. Eles devem ter origem verificável, publicação informada e identificador SeqDocumento/seqDocumento compatível com os nomes dos TXT. Não use material sigiloso. A obtenção dos textos e a triagem jurídica são etapas distintas da coleta de metadados DataJud.

Na raiz do clone, após instalar as dependências:

```powershell
# Processar os textos locais arquivados; não consulta serviços externos.
.\backend\.venv\Scripts\python.exe .\tools\nlp_validation\run_nlp_local.py

# Preparar amostra e previsões congeladas.
.\backend\.venv\Scripts\python.exe .\tools\nlp_validation\nlp_validation.py prepare

# Abrir a ferramenta de revisão neste computador.
.\backend\.venv\Scripts\python.exe .\tools\nlp_validation\nlp_review_server.py

# Avaliar depois das revisões humanas.
.\backend\.venv\Scripts\python.exe .\tools\nlp_validation\nlp_validation.py evaluate

# Diagnóstico opcional de um único revisor, sem aprovação de liberação.
.\backend\.venv\Scripts\python.exe .\tools\nlp_validation\nlp_validation.py evaluate --single-reviewer seu-identificador

# Testes de engenharia; usam dados sintéticos temporários.
.\backend\.venv\Scripts\python.exe -m unittest discover -s tools/nlp_validation -p test_nlp_validation.py -v
```

A revisão funciona em http://127.0.0.1:8766/. Selecione e classifique os trechos no texto completo. As previsões não são mostradas aos revisores. Cada pessoa deve usar seu próprio identificador. Dois nomes da mesma pessoa não são duas revisões independentes. É possível começar com um único revisor e usar o diagnóstico separado.

A referência final exige duas revisões completas e um terceiro identificador para adjudicação. As identidades são autodeclaradas; o programa não certifica qualificação nem independência. Alterações nas revisões invalidam uma adjudicação antiga, e o histórico é preservado.

As métricas comparam categoria e limites Unicode exatos: precisão, recall e F1 por categoria, separados entre desenvolvimento e teste. Ausência de revisão gera métricas nulas, não um acerto perfeito. Não se pontua adoção pelo julgador como funcionalidade validada, pois o extrator não a prevê. Uma conclusão semântica exige avaliação própria.

A amostra técnica é estratificada por ano, tribunal e extensão; seleção temática, variedade de resultados e elegibilidade ainda precisam de revisão. Textos idênticos são deduplicados. Decisões com process_number informado, ou processo nos metadados STJ, permanecem no mesmo lado da divisão. Sem identificação do processo, não se garante agrupamento de decisões distintas do mesmo processo. Com menos de 20 grupos, todos os textos ficam em desenvolvimento.

Os limites em criteria.json são propostas iniciais: 100 documentos, 20 documentos de teste adjudicados, STJ e TJDFT em todos os anos de 2016–2026, dez ocorrências humanas de cada categoria no teste, precisão de 90% e recall de 80%. São critérios do piloto, não um padrão jurídico ou garantia estatística. Aprovação de critérios e fontes fica pendente até o responsável preencher as referências. Não altere os limites após ver o teste apenas para obter aprovação.

O avaliador não aprova evidências no banco principal, não publica na Render e não libera automaticamente produção. Não usa previsões do próprio NLP como referência humana. Cada nova versão dos textos, regras ou previsões gera uma identidade de amostra própria.
