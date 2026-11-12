import { useEffect, useId, useRef, useState } from 'react'
import { nlpRequest, reportUrl, safeOfficialUrl } from './nlpApi'
import './nlp.css'
import { thesisTitle, thesisSummary } from './thesisPresentation'

const sourceLabels = { datajud: 'DataJud (metadados)', tjdft_jurisprudence: 'Jurisprudência TJDFT', stj_jurisprudence: 'Jurisprudência STJ', stj_precedent: 'Precedentes STJ', bdjur_doctrine: 'Doutrina BDJur' }
const outcomeLabels = { granted: 'Provido', denied: 'Desprovido', partial: 'Parcial', not_admitted: 'Não admitido', partial_knowledge: 'Conhecido em parte', ambiguous: 'Ambíguo', unknown: 'Desconhecido', outside_appellate_degree: 'Fora do grau recursal' }
const sourceStates = { available: 'Disponível na última consulta', changed: 'Fonte alterada; trecho da versão arquivada', not_found: 'Não encontrada na última consulta', removed: 'Remoção registrada', temporarily_unavailable: 'Temporariamente indisponível', restricted: 'Acesso restrito' }
const populationLabels = { decision_text: 'Textos de decisões', precedent: 'Precedentes', doctrine: 'Doutrina' }

function useRemote(key, load) {
  const [state, setState] = useState({ key: null, status: 'loading' })
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    let active = true
    const timer = setTimeout(() => controller.abort(), 20000)
    load(controller.signal).then(data => {
      if (active) setState({ key, status: 'ready', data })
    }).catch(error => {
      if (active) setState({ key, status: 'error', error: error.name === 'AbortError' ? 'A consulta demorou demais. Tente novamente.' : error.message })
    }).finally(() => clearTimeout(timer))
    return () => { active = false; clearTimeout(timer); controller.abort() }
    // The key contains all loader inputs; closure identity is intentionally excluded.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, retry])
  return [state.key === key ? state : { status: 'loading' }, () => setRetry(value => value + 1)]
}

function Feedback({ state, retry }) {
  if (state.status === 'loading') return <p role="status">Carregando evidências…</p>
  if (state.status === 'error') return <div role="alert"><p>{state.error}</p><button type="button" className="secondary-button" onClick={retry}>Tentar novamente</button></div>
  return null
}

function Source({ item }) {
  const link = safeOfficialUrl(item.official_url)
  const annotation = item.effective
  return <article className="nlp-source">
    <h4>{item.document_metadata?.title || item.document_id}</h4>
    <p>{item.court} · Documento {item.document_id} · Revisão aprovada</p>
    {annotation.segments.map((segment, index) => <div key={index}>
      <blockquote>{segment.text}</blockquote>
      <p>Trecho exato · caracteres Unicode {segment.start} a {segment.end} (fim exclusivo){segment.locator?.page != null ? ` · página ${segment.locator.page}` : ' · página não localizada'}</p>
    </div>)}
    <p>{sourceStates[item.source_state] || 'Disponibilidade não informada'}{item.source_checked_at && ` · consultada em ${new Date(item.source_checked_at).toLocaleString('pt-BR')}`}</p>
    {link ? <a href={link} target="_blank" rel="noreferrer">Abrir documento na fonte oficial (nova aba)</a> : <p>Link oficial específico não disponível.</p>}
    <p>Adoção pelo julgador: {annotation.context?.adoption?.value || 'não determinada'}.</p>
    {(annotation.warnings || []).includes('low_confidence') && <p><strong>Baixa confiança da extração.</strong> Consulte o trecho e a decisão de qualidade; a frequência não resolve esta incerteza.</p>}
    <p>{annotation.confidence?.score == null ? 'Pontuação da extração não disponível.' : 'A pontuação da extração não estima êxito judicial.'}</p>
    <details><summary>Versões e rastreabilidade da evidência</summary><dl>
      <dt>Evidência</dt><dd>{item.id}</dd><dt>Revisão congelada</dt><dd>{item.revision} · {item.revision_id || 'original'}</dd>
      <dt>Versão do texto</dt><dd>{item.text_version_id}</dd><dt>SHA-256 do texto</dt><dd>{item.text_sha256}</dd>
      <dt>Versão da fonte</dt><dd>{item.source?.source_version || 'não informada'}</dd>
      <dt>Extração</dt><dd>{item.extraction_id}</dd><dt>Pipeline, modelo e regras</dt><dd><pre>{JSON.stringify(item.pipeline, null, 2)}</pre></dd>
      <dt>Observação da fonte</dt><dd>{item.source_observation_id}</dd>
      <dt>Cobertura da extração</dt><dd><pre>{JSON.stringify(item.coverage || {}, null, 2)}</pre></dd>
      <dt>Limitações registradas</dt><dd><pre>{JSON.stringify(item.warnings || [], null, 2)}</pre></dd>
    </dl></details>
  </article>
}

function Sources({ snapshotId, resource, groupId, population }) {
  const [cursor, setCursor] = useState('')
  const statusRef = useRef(null)
  const moveFocus = useRef(false)
  const path = `analysis-snapshots/${snapshotId}/${resource}/${groupId}/sources/?population=${population}&limit=10${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`
  const [state, retry] = useRemote(path, signal => nlpRequest(path, { signal }))
  useEffect(() => { if (state.data && moveFocus.current) { statusRef.current?.focus(); moveFocus.current = false } }, [state.data])
  function navigate(value) { moveFocus.current = true; setCursor(value) }
  return <div aria-busy={state.status === 'loading'}><Feedback state={state} retry={retry} />
    {state.data && <><p role="status" tabIndex={-1} ref={statusRef}>{state.data.total_items} trechos no snapshot.</p>
      {state.data.items.map(item => <Source key={item.id} item={item} />)}
      {cursor && <button type="button" className="secondary-button" onClick={() => navigate('')}>Primeira página de fontes</button>}
      {state.data.next_cursor && <button type="button" className="secondary-button" onClick={() => navigate(state.data.next_cursor)}>Próxima página de fontes</button>}
    </>}
  </div>
}


function Rankings({ snapshot, population, resource, order }) {
  const [cursor, setCursor] = useState('')
  const [selectedId, setSelectedId] = useState(null)
  const evidenceId = useId()
  const statusRef = useRef(null)
  const moveFocus = useRef(false)
  const path = `analysis-snapshots/${snapshot.snapshot_id}/${resource}/?population=${population}&order=${order}&limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`
  const [state, retry] = useRemote(path, signal => nlpRequest(path, { signal }))
  useEffect(() => { if (state.data && moveFocus.current) { statusRef.current?.focus(); moveFocus.current = false } }, [state.data])
  function navigate(value) { moveFocus.current = true; setSelectedId(null); setCursor(value) }
  const selected = state.data?.items.find(item => item.id === selectedId)
  const maximum = Math.max(1, ...(state.data?.items || []).map(item => item.document_count || 0))
  return <div aria-busy={state.status === 'loading'}><Feedback state={state} retry={retry} />
    {state.data && <><p role="status" tabIndex={-1} ref={statusRef}>{state.data.total_items} grupos por texto literal. Não há inferência de equivalência jurídica.</p>
      {!state.data.items.length && <p>Nenhuma ocorrência liberada nesta população. A ausência de extração não comprova ausência de tese no documento.</p>}
      <div className="nlp-evidence-grid">
        <article className="thesis-card"><span className="section-kicker">Frequência · NLP + revisão</span><h3>{resource === 'theses' ? 'Principais teses no recorte' : 'Principais fundamentos no recorte'}</h3><p>{population === 'decision_text' ? 'Decisões com evidência revisada; contagem por documento distinto, não por processo.' : 'Documentos distintos nesta população; não representam casos julgados.'}</p>
          <ol className="nlp-ranking compact-theses">{state.data.items.map(item => <li className={`thesis-row${selectedId === item.id ? ' is-selected' : ''}`} key={item.id}>
            <h4 className="nlp-compact-title">{thesisTitle(item)}</h4>
            <div className="thesis-distribution"><div className="thesis-track"><div className="thesis-track-fill" style={{ width: `${(item.document_count || 0) / maximum * 100}%` }} /></div><span className="thesis-count">{item.document_count} {item.document_count === 1 ? 'documento' : 'documentos'}</span></div>
            <details className="thesis-full-text"><summary>Resumo da tese</summary><p>{thesisSummary({ title: item.label })}</p><details><summary>Texto identificado pelo NLP</summary><p>{item.label}</p></details></details>
            <button className="text-button nlp-select-evidence" type="button" aria-expanded={selectedId === item.id} aria-controls={evidenceId} onClick={() => setSelectedId(current => current === item.id ? null : item.id)}>Ver fontes<span className="nlp-visually-hidden"> — {thesisTitle(item)}</span> →</button>
          </li>)}</ol>
        </article>
        <article className="related-card" id={evidenceId}><span className="section-kicker">Evidências · fonte rastreável</span><h3>Decisões relacionadas</h3>
          {selected ? <><h4>{thesisTitle(selected)}</h4><p>{selected.document_count} documentos distintos · {selected.evidence_count} trechos. A frequência não comprova adoção pelo julgador.</p><Sources key={selected.id} snapshotId={snapshot.snapshot_id} resource={resource} groupId={selected.id} population={population} /></> : <p role="status">Selecione “Ver fontes” em uma tese para consultar os trechos e documentos que sustentam a contagem.</p>}
        </article>
      </div>
      {cursor && <button className="secondary-button" type="button" onClick={() => navigate('')}>Primeira página</button>}
      {state.data.next_cursor && <button className="secondary-button" type="button" onClick={() => navigate(state.data.next_cursor)}>Próxima página</button>}
    </>}
  </div>
}

function FrozenResults({ snapshot }) {
  const [population, setPopulation] = useState('decision_text')
  const [resource, setResource] = useState('theses')
  const [order, setOrder] = useState('-document_count')
  const [exportError, setExportError] = useState('')
  const selected = snapshot.populations[population]
  async function exportManifest() {
    try {
      setExportError('')
      const payload = await nlpRequest(`analysis-snapshots/${snapshot.snapshot_id}/export/`)
      const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }))
      const anchor = document.createElement('a')
      anchor.href = url; anchor.download = `datumlex-evidencias-${snapshot.snapshot_id}.json`; anchor.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (error) { setExportError(error.message) }
  }
  return <>
    {snapshot.data_mode !== 'live' && <p role="status"><strong>Fixture de demonstração — dados sintéticos; sem validade jurídica.</strong></p>}
    <p>{snapshot.disclaimer}</p>
    <details><summary>Como este ranking é calculado</summary><p>A ordem padrão usa a quantidade de documentos distintos com trecho literal igual. Repetições no mesmo documento não aumentam essa contagem. O desempate usa o identificador estável do grupo. As populações de decisões, precedentes e doutrina são separadas. Somente evidências aprovadas na revisão e liberadas pela política de qualidade entram na lista. Um fundamento não é automaticamente associado a uma tese.</p></details>
    <p>Corpus carregado parcial. {snapshot.exclusions.unmapped_documents} documentos sem mapeamento revisado; {snapshot.exclusions.quality_blocked} bloqueados por qualidade; {snapshot.exclusions.missing_text} sem texto processável.</p>
    <div className="nlp-controls">
      <label>População<select aria-label="População" value={population} onChange={event => setPopulation(event.target.value)}>{Object.entries(populationLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>Conteúdo<select aria-label="Conteúdo" value={resource} onChange={event => setResource(event.target.value)}><option value="theses">Teses</option><option value="grounds">Fundamentos</option></select></label>
      <label>Ordenação<select aria-label="Ordenação" value={order} onChange={event => setOrder(event.target.value)}><option value="-document_count">Mais documentos</option><option value="document_count">Menos documentos</option><option value="label">Texto em ordem alfabética</option></select></label>
    </div>
    <p>{selected.documents_in_scope} documentos no recorte mapeado; {selected.documents_quality_released} liberados; {selected.denominator} no denominador exibido. Campo temporal: {selected.period_field}.</p>
    {selected.status === 'unavailable' ? <p role="status">Análise indisponível: requer fonte autorizada, mapeamento revisado e decisão de qualidade #112. Nenhum ranking foi fabricado.</p> : selected.status === 'empty' ? <p role="status">Nenhum documento corresponde à seleção nesta população. Ajuste os filtros.</p> : <Rankings key={`${snapshot.snapshot_id}-${population}-${resource}-${order}`} snapshot={snapshot} population={population} resource={resource} order={order} />}
    <details><summary>Contexto congelado e integração com PDF</summary><p>O relatório usa este snapshot completo, sem consultar revisões atuais.</p><a href={reportUrl(snapshot.snapshot_id)} target="_blank" rel="noreferrer">Abrir relatório completo para salvar em PDF (nova aba)</a><pre>{JSON.stringify(snapshot.context, null, 2)}</pre><p>Snapshot: {snapshot.snapshot_id}<br />Consulta: {snapshot.query_id}<br />SHA-256: {snapshot.sha256}</p><button className="secondary-button" type="button" onClick={exportManifest}>Baixar evidências congeladas (JSON)</button>{exportError && <p role="alert">{exportError}</p>}</details>
  </>
}

export default function NlpPanel({ contextKey }) {
  const [choices, setChoices] = useState(null)
  const [applied, setApplied] = useState(null)
  const [version, setVersion] = useState(0)
  const [options, retryOptions] = useRemote('filter-options/', signal => nlpRequest('filter-options/', { signal }))
  const inherited = JSON.parse(contextKey)
  const resolved = { ...(options.data?.default_context || {}), ...inherited, ...(applied || {}) }
  const key = JSON.stringify(resolved)
  const [state, retry] = useRemote(`${key}-${version}-${options.status}`, async signal => {
    if (!options.data) return null
    return nlpRequest('analysis-snapshots/', { signal, body: { context: resolved } })
  })
  const selected = choices || resolved
  function toggle(field, value, checked) {
    setChoices({ ...selected, [field]: checked ? [...selected[field], value] : selected[field].filter(item => item !== value) })
  }
  return <section className="nlp-panel" aria-labelledby="nlp-title">
    <h2 id="nlp-title">Teses identificadas nas decisões</h2>
    <p>Tribunais, assunto e período seguem o recorte aplicado acima. Fontes e desfechos abaixo filtram somente este painel de NLP; as taxas DataJud mantêm sua própria população.</p>
    <Feedback state={options} retry={retryOptions} />
    {options.data && <><form onSubmit={event => { event.preventDefault(); setApplied({ sources: selected.sources, outcomes: selected.outcomes }); setVersion(value => value + 1) }}>
      <div className="nlp-controls"><fieldset><legend>Fontes do NLP</legend>{options.data.sources.map(source => <label key={source.id}><input type="checkbox" checked={selected.sources.includes(source.id)} onChange={event => toggle('sources', source.id, event.target.checked)} />{sourceLabels[source.id]} · liberação por documento</label>)}</fieldset>
        <fieldset><legend>Desfechos exibidos nos textos de decisões</legend>{options.data.outcomes.map(value => <label key={value}><input type="checkbox" checked={selected.outcomes.includes(value)} onChange={event => toggle('outcomes', value, event.target.checked)} />{outcomeLabels[value]}</label>)}</fieldset></div>
      <button className="apply-button" type="submit">Aplicar filtros de NLP</button> <button className="secondary-button" type="button" onClick={() => { setChoices(null); setApplied(null); setVersion(value => value + 1) }}>Restaurar padrões do NLP</button>
    </form>
    <div aria-busy={state.status === 'loading'}><Feedback state={state} retry={retry} />{state.data && <FrozenResults key={state.data.snapshot_id} snapshot={state.data} />}</div></>}
  </section>
}
