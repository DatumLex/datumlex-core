import { useEffect, useState } from 'react'
import { getData } from './api'

const kinds = { jurisprudence: 'Jurisprudência', precedent: 'Precedentes', doctrine: 'Doutrina' }
const formats = { full_text: 'Inteiro teor', ementa: 'Ementa', publication_excerpt: 'Publicação', doctrine_article: 'Artigo', doctrine_collection: 'Coletânea', precedent_reference: 'Referência de precedente' }
const count = (value) => new Intl.NumberFormat('pt-BR').format(value || 0)
const dateLabel = (value) => value ? new Date(`${value}T12:00:00`).toLocaleDateString('pt-BR') : 'Data não informada'

export default function CorpusPanel({ court, start, end }) {
  const [topic, setTopic] = useState('')
  const [category, setCategory] = useState('jurisprudence')
  const [completeOnly, setCompleteOnly] = useState(false)
  const [includeUndated, setIncludeUndated] = useState(true)
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [retry, setRetry] = useState(0)
  const [state, setState] = useState({ loading: true, data: null, error: '' })
  useEffect(() => {
    const controller = new AbortController()
    let active = true
    const timer = setTimeout(() => controller.abort(), 30000)
    async function load() {
      setState({ loading: true, data: null, error: '' })
      try {
        const data = await getData('corpus', { court, start, end, topic, category,
          complete_only: String(completeOnly), include_undated: String(includeUndated),
          q: query, page, page_size: 12 }, controller.signal)
        if (!data.counts || !Array.isArray(data.topics) || !Array.isArray(data.items)) throw new Error('Resposta do acervo inválida.')
        if (active) setState({ loading: false, data, error: '' })
      } catch (error) {
        if (active) setState({ loading: false, data: null, error: error.name === 'AbortError' ? 'A consulta demorou. Tente novamente.' : error.message })
      } finally { clearTimeout(timer) }
    }
    load()
    return () => { active = false; clearTimeout(timer); controller.abort() }
  }, [court, start, end, topic, category, completeOnly, includeUndated, query, page, retry])
  const data = state.data
  const topicLabel = data?.topics.find((item) => item.id === topic)?.label
  const completeTopics = data?.topics.filter((item) => item.has_all_three) || []
  function chooseTopic(value) { setTopic(value); setPage(1) }
  return <section className="corpus-panel" aria-labelledby="corpus-title" aria-busy={state.loading}>
    <header className="corpus-heading"><span className="eyebrow">Responsabilidade Civil</span><h2 id="corpus-title">Acervo por assunto</h2><p>Explore decisões, precedentes e doutrina. Assuntos com material nos três grupos aparecem primeiro.</p></header>
    <p className="chart-note">Tribunais: {court}. O período usa julgamento ou publicação quando informados. A doutrina é bibliografia compartilhada, sem atribuição a tribunal. O assunto CNJ da visão geral não restringe esta seleção temática.</p>
    <div className="corpus-counts" aria-label="Documentos disponíveis por tipo">{Object.entries(kinds).map(([key, label]) => <article className="corpus-count" key={key}><strong>{state.loading ? '—' : count(data?.counts[key])}</strong><h3>{label}</h3><small>Documentos únicos no recorte do acervo</small></article>)}</div>
    <form className="corpus-search" onSubmit={(event) => { event.preventDefault(); setQuery(search.trim()); setPage(1) }}>
      <label>Buscar no título<input type="search" maxLength={120} value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Ex.: transporte aéreo" /></label>
      <button className="secondary-button" type="submit">Buscar</button>
    </form>
    <div className="corpus-options"><label><input type="checkbox" checked={completeOnly} onChange={(event) => { setCompleteOnly(event.target.checked); setPage(1) }} /> Somente assuntos com os três tipos</label><label><input type="checkbox" checked={includeUndated} onChange={(event) => { setIncludeUndated(event.target.checked); setPage(1) }} /> Incluir referências sem data confirmada</label></div>
    {state.error && <div role="alert" className="corpus-message"><p>{state.error}</p><button type="button" className="secondary-button" onClick={() => setRetry((value) => value + 1)}>Tentar novamente</button></div>}
    {state.loading && <p role="status">Consultando o acervo local…</p>}
    {data && <>
      <p className="chart-note">{completeTopics.length ? `${completeTopics.length} assuntos têm material nos três grupos.` : 'Ainda não há assunto com material nos três grupos neste recorte.'} Os dez temas são uma seleção inicial, não um ranking nacional. Um documento pode aparecer em mais de um assunto.</p>
      <div className="corpus-topics" role="group" aria-label="Assuntos de Responsabilidade Civil"><button type="button" aria-pressed={!topic} onClick={() => chooseTopic('')}>Todos os assuntos</button>{data.topics.filter((item) => !completeOnly || item.has_all_three).map((item) => <button key={item.id} type="button" aria-pressed={topic === item.id} onClick={() => chooseTopic(item.id)}><strong>{item.label}</strong><span>{item.has_all_three ? 'Três tipos disponíveis · ' : ''}J: {count(item.counts.jurisprudence)} · P: {count(item.counts.precedent)} · D: {count(item.counts.doctrine)}</span></button>)}</div>
      <div className="corpus-categories" role="group" aria-label="Tipo de conteúdo">{Object.entries(kinds).map(([key, label]) => <button className="secondary-button" type="button" key={key} aria-pressed={category === key} onClick={() => { setCategory(key); setPage(1) }}>{label} ({count(data.counts[key])})</button>)}</div>
      <h3>{kinds[category]}{topicLabel ? ` · ${topicLabel}` : ''}</h3>
      {data.coverage.undated > 0 && <p className="corpus-message">{count(data.coverage.undated)} referências no recorte estão sem data confirmada. Elas não comprovam cobertura do período selecionado.</p>}
      {data.items.length ? <div className="corpus-results">{data.items.map((item) => <article className="corpus-result" key={item.id}>
        <span className="section-kicker">{formats[item.content_kind] || item.content_kind} · {item.court || item.source_name}</span><h4>{item.title}</h4>
        {item.authors.length > 0 && <p>{item.authors.join(', ')}</p>}
        <p className="chart-note">{dateLabel(item.date)}{!item.period_confirmed ? ' · período não confirmado' : ''} · {item.review_status === 'approved' ? 'Fonte revisada' : 'Revisão da fonte pendente'}</p>
        {item.processing_status === 'awaiting_nlp' && <p className="chart-note">Texto coletado; processamento NLP pendente.</p>}
        <p className="chart-note">Tema sugerido por termos; vínculo jurídico entre documentos não validado.</p>
        {item.excerpt && <details><summary>Consultar trecho inicial</summary><p className="corpus-excerpt">{item.excerpt}</p></details>}
        {item.source_url && /^https?:\/\//i.test(item.source_url) ? <a href={item.source_url} target="_blank" rel="noreferrer">Abrir fonte original ↗</a> : <p className="chart-note">Link público não informado.</p>}
      </article>)}</div> : <p className="corpus-message">Nenhum documento deste tipo corresponde aos filtros. Tente outro assunto ou confira os demais tipos.</p>}
      <div className="corpus-pagination"><button className="secondary-button" type="button" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Anterior</button><span>Página {page} · {count(data.pagination.total)} documentos</span><button className="secondary-button" type="button" disabled={!data.pagination.has_next} onClick={() => setPage((value) => value + 1)}>Próxima</button></div>
      <p className="chart-note">O acervo apresenta fontes já indexadas. Classificação temática pendente de revisão jurídica. Não representa conclusão do NLP nem aderência a precedentes.</p>
    </>}
  </section>
}
