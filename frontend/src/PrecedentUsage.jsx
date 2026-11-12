const number = value => new Intl.NumberFormat('pt-BR').format(value || 0)
const labels = { applied: 'Aplicação explícita', not_applied: 'Afastamento explícito', mentioned: 'Somente citação', ambiguous: 'Contexto ambíguo' }

export default function PrecedentUsage({ usage }) {
  if (!usage) return null
  return <article className="source-card">
    <h3>Aplicação de precedentes identificada nos textos públicos</h3>
    <p>{usage.application_rate == null ? 'Sem sinal explícito para calcular o percentual.' : `${(usage.application_rate * 100).toFixed(1).replace('.', ',')}% de aplicações entre os vínculos explícitos.`} Base: {number(usage.denominator)} pares de documento e precedente.</p>
    <p>{Object.entries(labels).map(([key, label]) => `${label}: ${number(usage.counts[key])}`).join(' · ')}</p>
    <p className="chart-note">{number(usage.coverage.documents_analyzed)} ementas analisadas por data de julgamento. Sem data: {number(usage.coverage.undated)}; sem assunto confirmado: {number(usage.coverage.unconfirmed_subject)}; sem ementa delimitada: {number(usage.coverage.missing_ementa)}.</p>
    <p className="chart-note">{usage.disclaimer}</p>
    <details className="chart-table"><summary>Conferir trechos e fontes ({number(usage.pagination.total)} vínculos)</summary>
      {usage.items.length ? <ul className="source-links">{usage.items.map(item => <li key={item.id}>
        <strong>{labels[item.status]} · {item.authority_literal}</strong>
        <blockquote>{item.excerpt}</blockquote>
        <a href={item.source_url} target="_blank" rel="noreferrer">Abrir acórdão original · {item.court} · {item.decision_date}</a>
        <p className="chart-note">Ementa, linha {item.line}; caracteres {item.start} a {item.end}. Método: {item.rule_version}. Texto SHA-256: {item.text_sha256}</p>
      </li>)}</ul> : <p>Nenhuma referência STJ identificável nas ementas elegíveis.</p>}
      {usage.pagination.has_next && <p>Exibindo os primeiros {usage.pagination.page_size} vínculos; as contagens incluem todos os resultados.</p>}
    </details>
  </article>
}
