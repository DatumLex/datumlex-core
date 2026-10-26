import { safeOfficialUrl } from './nlpApi'
import { formatProcessIdentifier } from './processIdentifier'

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
    <h4>Processos citados no Pangea</h4>
    <p>Abra a referência para consultar a tese e os processos indicados pela fonte.</p>
    <details><summary>Como interpretar estas citações</summary><p>A citação não comprova relação com um processo TJDFT nem aderência à tese. Datas de julgamento não informadas não recebem o filtro de período.</p></details>
    {citations.length ? <><p>{citations.length} citações nas referências carregadas{selectedIdentifiers ? ' da tese selecionada' : ''}; mostrando até 8.</p>
      <div className="related-list">{citations.slice(0, 8).map(item => {
        const decisionUrl = safeOfficialUrl(item.url)
        const referenceUrl = sourceUrl(item.reference.source_url)
        return <article className="related-item source-citation-item" key={`${item.reference.identifier}:${item.identifier}`}>
          <div className="source-citation-content"><span className="review-pending-badge">Citação do Pangea</span>
            <h4>Processo {formatProcessIdentifier(item.identifier)}</h4><p>Referência: {item.reference.title}</p>
            {decisionUrl && <p><a href={decisionUrl} target="_blank" rel="noreferrer">Consultar processo no STJ ↗</a></p>}
            {referenceUrl && <a href={referenceUrl} target="_blank" rel="noreferrer">Ver referência no Pangea ↗</a>}
            {!decisionUrl && !referenceUrl && <p>A fonte não disponibilizou um link para consulta.</p>}
            {item.locator && <details><summary>Rastreabilidade</summary><small>{item.locator}</small></details>}
          </div>
        </article>
      })}</div></> : <p>Nenhum processo citado nas referências carregadas para esta seleção. Isso não significa ausência de decisões sobre o tema.</p>}
  </section>
}
