import { safeOfficialUrl } from './nlpApi'

function sourceUrl(value) {
  const official = safeOfficialUrl(value)
  if (official) return official
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && !url.username && !url.password && url.hostname === 'pangeabnp.pdpj.jus.br' ? url.href : null
  } catch { return null }
}

export default function SourceDecisions({ references = [], selectedIdentifiers = null }) {
  const seen = new Set()
  const citations = references.filter(reference => !selectedIdentifiers || selectedIdentifiers.has(reference.identifier))
    .flatMap(reference => (Array.isArray(reference.related_decisions) ? reference.related_decisions : [])
      .filter(decision => decision && typeof decision.identifier === 'string' && decision.identifier.trim())
      .map(decision => ({ ...decision, reference })))
    .filter(item => {
      const key = `${item.reference.identifier}:${item.identifier.trim()}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  return <section className="source-citations" aria-label="Processos citados pela fonte">
    <h4>Processos citados pela fonte</h4>
    <p>São processos indicados nas referências do Pangea. A citação não comprova relação com um processo TJDFT nem aderência à tese. Datas de julgamento não informadas não recebem o filtro de período.</p>
    {citations.length ? <><p>{citations.length} citações nas referências carregadas{selectedIdentifiers ? ' da tese selecionada' : ''}; mostrando até 8.</p>
      <div className="related-list">{citations.slice(0, 8).map(item => {
        const decisionUrl = safeOfficialUrl(item.url)
        const referenceUrl = sourceUrl(item.reference.source_url)
        return <article className="related-item evidence-item" key={`${item.reference.identifier}:${item.identifier}`}>
          <div className="evidence-item-content"><span className="review-pending-badge">Citado na fonte · vínculo local não confirmado</span>
            <h4>{item.identifier}</h4><p>{item.reference.title}</p><small>{item.locator || 'Localizador não informado'}</small>
            {decisionUrl ? <p><a href={decisionUrl} target="_blank" rel="noreferrer">Consultar processo no STJ ↗</a></p> : <p>Link específico do processo não disponibilizado.</p>}
            {referenceUrl && <a href={referenceUrl} target="_blank" rel="noreferrer">Ver referência no Pangea ↗</a>}
          </div>
        </article>
      })}</div></> : <p>Nenhum processo citado nas referências carregadas para esta seleção. Isso não significa ausência de decisões sobre o tema.</p>}
  </section>
}
