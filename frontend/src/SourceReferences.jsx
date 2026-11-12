import { safeOfficialUrl } from './nlpApi'

function safeSourceUrl(value) {
  const official = safeOfficialUrl(value)
  if (official) return official
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && url.hostname === 'pangeabnp.pdpj.jus.br' && !url.username && !url.password ? url.href : null
  } catch { return null }
}

export default function SourceReferences({ groups = [], references = [], selectedIdentifiers }) {
  const sources = new Map()
  for (const source of [...references, ...groups.flatMap(group => group.source_references || [])]) {
    if (!source.identifier || (selectedIdentifiers && !selectedIdentifiers.has(source.identifier))) continue
    sources.set(source.identifier, { ...sources.get(source.identifier), ...source })
  }
  return <section className="thesis-related-sources"><h4>Fontes das teses{selectedIdentifiers ? ' selecionadas' : ' no recorte'}</h4>
    {sources.size ? <ul>{[...sources.values()].map(source => {
      const url = safeSourceUrl(source.source_url)
      return <li key={source.identifier}><strong>{source.source_institution || 'Fonte'} · {source.identifier}</strong>{source.title && <details><summary>Detalhes da referência</summary><p>{source.title}</p>{source.source_locator && <small>{source.source_locator}</small>}</details>}{url ? <a href={url} target="_blank" rel="noreferrer">Abrir fonte original ↗</a> : <small>Link original indisponível.</small>}</li>
    })}</ul> : <p>Nenhuma fonte identificada para esta seleção.</p>}
  </section>
}
