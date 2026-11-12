import { useState } from 'react'
import { thesisTitle, thesisSummary } from './thesisPresentation'

export default function ThesisGroups({ groups = [], selectedId, onSelect }) {
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(0)
  const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR')
  const filtered = groups.filter(group => normalize([group.label, group.title, ...(group.source_references || []).map(ref => ref.identifier)].filter(Boolean).join(' ')).includes(normalize(query)))
  const visible = filtered.slice(page * 25, (page + 1) * 25)
  const maximum = Math.max(1, ...groups.map(group => group.case_count || 0))
  if (!groups.length) return <p role="status">Nenhuma tese disponível neste recorte.</p>
  return <><label className="thesis-search">Buscar tese<input type="search" value={query} onChange={event => { setQuery(event.target.value); setPage(0) }} placeholder="Tema, expressão ou referência" /></label><p role="status">{filtered.length} de {groups.length} teses · página {page + 1}</p>
  <ol className="thesis-list compact-theses">{visible.map(group => {
    const statement = group.title || group.label || group.titulo || 'Tese sem título'
    return <li key={group.id} className={`thesis-row${selectedId === group.id ? ' is-selected' : ''}`}>
      <button type="button" className="thesis-row-main" aria-pressed={selectedId === group.id} onClick={() => onSelect(group.id)}><strong>{thesisTitle(group)}</strong></button>
      <div className="thesis-distribution"><div className="thesis-track"><div className="thesis-track-fill" style={{ width: `${Math.max(0, (group.case_count || 0) / maximum * 100)}%` }} /></div><span className="thesis-count">{new Intl.NumberFormat('pt-BR').format(group.case_count || 0)} {group.case_count === 1 ? 'referência' : 'referências'}</span></div>
      {!group.approved && <span className="review-pending-badge">Revisão pendente</span>}
      <details className="thesis-full-text"><summary>Resumo da tese</summary><p className="thesis-statement">{thesisSummary(group)}</p>{group.nlp && <small>Resumo extrativo · classificação por termos: {group.nlp.matched_terms.join(", ") || "tema não identificado"}. Sujeita a revisão.</small>}<details><summary>Ler enunciado integral</summary><p className="thesis-statement">{statement}</p></details></details>
    </li>
  })}</ol><div className="thesis-pagination">{page > 0 && <button type="button" className="secondary-button" onClick={() => setPage(value => value - 1)}>Teses anteriores</button>}{(page + 1) * 25 < filtered.length && <button type="button" className="secondary-button" onClick={() => setPage(value => value + 1)}>Próximas teses</button>}</div></>
}
