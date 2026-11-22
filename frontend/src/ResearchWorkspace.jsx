import { useEffect, useRef, useState } from 'react'
import {
  BookOpen,
  Bookmark,
  ChevronRight,
  Database,
  Download,
  FolderSearch,
  MessageSquare,
  Scale,
  Search,
  Send,
  SlidersHorizontal,
  Sparkles,
  X,
} from 'lucide-react'
import { getData } from './api'
import App from './App'
import './research.css'

const api = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')
const pages = {
  search: ['Pesquisa', 'Painel de pesquisa', Search],
  chat: ['Chat da pesquisa', 'Chat da pesquisa', MessageSquare],
  corpus: ['Acervo por assunto', 'Acervo por assunto', BookOpen],
  precedents: ['Precedentes e teses', 'Precedentes e teses', Scale],
  notebook: ['Caderno', 'Caderno de pesquisa', Bookmark],
  coverage: ['Fontes e cobertura', 'Fontes e cobertura', Database],
  legacy: ['Análise detalhada', 'Análise detalhada', FolderSearch],
}
const sourceLabels = {
  datajud: 'DataJud',
  jurisprudence: 'Decisões',
  precedent: 'Precedentes',
  doctrine: 'Doutrina',
}
const kinds = {
  jurisprudence: 'Decisão',
  precedent: 'Precedente',
  doctrine: 'Doutrina',
  link: 'Vínculo em ementa',
}
const results = {
  granted: 'Provido',
  denied: 'Desprovido',
  partial: 'Parcial',
  not_admitted: 'Não admitido',
  partial_knowledge: 'Conhecido em parte',
  ambiguous: 'Ambíguo',
  unknown: 'Sem resultado',
  outside_appellate_degree: 'Fora do grau recursal',
}
const prompts = [
  'Como foi calculada a taxa de provimento?',
  'Quais precedentes foram aplicados ou afastados?',
  'Que doutrina aparece nesta pesquisa?',
  'Como evoluiu o volume por trimestre?',
]
const today = () =>
  new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Sao_Paulo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date())
const defaults = (courts) => ({
  court: [...courts].sort(),
  topics: [],
  subject: [],
  sources: Object.keys(sourceLabels),
  outcomes: Object.keys(results),
  start: '2016-01-01',
  end: today(),
  undated: true,
})
const number = (n) => (n == null ? '—' : n.toLocaleString('pt-BR'))
const date = (d) => (d ? d.split('-').reverse().join('/') : 'Sem data')
const rate = (value) =>
  value == null ? '—' : value.toLocaleString('pt-BR', { style: 'percent', maximumFractionDigits: 1 })
const pack = (filters) =>
  Object.fromEntries(
    Object.entries(filters).map(([key, value]) => [
      key,
      Array.isArray(value) ? [...value].sort().join(',') : String(value),
    ]),
  )
const emptyThread = { turns: [], draft: '', busy: false, error: '' }

function Choice({ name, title, options, draft, setDraft }) {
  return (
    <fieldset>
      <legend>{title}</legend>
      <div className="rw-choices">
        {Object.entries(options).map(([v, label]) => (
          <label key={v}>
            <input
              type="checkbox"
              checked={draft[name].includes(v)}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  [name]: e.target.checked ? [...draft[name], v] : draft[name].filter((x) => x !== v),
                })
              }
            />
            {label}
          </label>
        ))}
      </div>
    </fieldset>
  )
}
function Filters({ applied, courts, topics, subjects, onApply, onClose }) {
  const [draft, setDraft] = useState(applied)
  const [error, setError] = useState('')
  function submit(e) {
    e.preventDefault()
    if (
      !draft.court.length ||
      !draft.sources.length ||
      (draft.sources.includes('datajud') && !draft.outcomes.length) ||
      draft.start > draft.end
    ) {
      setError('Selecione tribunais, fontes e resultados válidos e confira a ordem das datas.')
      return
    }
    onApply(draft)
    onClose()
  }
  return (
    <form className="rw-filter-form" onSubmit={submit}>
      <Choice
        name="court"
        title="Tribunais autorizados"
        options={Object.fromEntries(courts.map((k) => [k, k]))}
        {...{ draft, setDraft }}
      />
      <div className="rw-dates">
        {[
          ['start', 'Data inicial'],
          ['end', 'Data final'],
        ].map(([k, l]) => (
          <label key={k}>
            {l}
            <input
              type="date"
              required
              min="2016-01-01"
              max={today()}
              value={draft[k]}
              onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
            />
          </label>
        ))}
      </div>
      <Choice name="topics" title="Temas do acervo e das ementas" options={topics} {...{ draft, setDraft }} />
      <Choice
        name="subject"
        title="Assuntos CNJ dos indicadores e das ementas"
        options={subjects}
        {...{ draft, setDraft }}
      />
      <Choice name="sources" title="Fontes" options={sourceLabels} {...{ draft, setDraft }} />
      <Choice name="outcomes" title="Resultados do DataJud" options={results} {...{ draft, setDraft }} />
      <label>
        <input
          type="checkbox"
          checked={draft.undated}
          onChange={(e) => setDraft({ ...draft, undated: e.target.checked })}
        />{' '}
        Incluir fontes do acervo sem data
      </label>
      {error && <p role="alert">{error}</p>}
      <div className="rw-actions">
        <button type="submit" className="apply-button">
          Aplicar filtros
        </button>
        <button type="button" className="secondary-button" onClick={() => setDraft(defaults(courts))}>
          Restaurar filtros
        </button>
      </div>
    </form>
  )
}
function Drawer({ title, children, onClose }) {
  const ref = useRef(null)
  useEffect(() => {
    const el = ref.current
    el.showModal()
    return () => el.close()
  }, [])
  return (
    <dialog ref={ref} className="rw-drawer" onCancel={onClose} aria-labelledby="rw-dialog-title">
      <header>
        <h2 id="rw-dialog-title">{title}</h2>
        <button type="button" className="rw-icon" aria-label="Fechar" onClick={onClose}>
          <X size={20} />
        </button>
      </header>
      {children}
    </dialog>
  )
}
function SourceRow({ doc, onOpen }) {
  const Icon = doc.kind === 'doctrine' ? BookOpen : doc.kind === 'precedent' ? Scale : FolderSearch
  return (
    <button className="rw-source" onClick={() => onOpen(doc)}>
      <span>
        <Icon size={18} />
      </span>
      <span>
        <small>
          {kinds[doc.kind]} · {doc.origin}
        </small>
        <strong>{doc.title}</strong>
        {doc.relation && <small>{doc.relation}</small>}
      </span>
      <ChevronRight size={16} />
    </button>
  )
}
function Paragraphs({ blocks, docs, onOpen }) {
  return blocks.map((p, i) => (
    <p key={i}>
      {p.text}
      {p.refs.map((id) => {
        const doc = docs.find((d) => d.id === id)
        return (
          doc && (
            <button
              className="rw-cite"
              key={id}
              aria-label={'Abrir ' + doc.title}
              onClick={() => onOpen(doc)}
            >
              {id.startsWith('V') ? 'Ementa' : id}
            </button>
          )
        )
      })}
    </p>
  ))
}
function History({ series }) {
  const grouped = new Map()
  for (const row of series) {
    const p = row.time__year + ' · T' + row.time__quarter
    grouped.set(p, (grouped.get(p) || 0) + row.count)
  }
  const maximum = Math.max(1, ...grouped.values())
  return (
    <details className="rw-history">
      <summary>Histórico por trimestre de ajuizamento</summary>
      {grouped.size ? (
        <div>
          {[...grouped].map(([period, n]) => (
            <div className="rw-bar" key={period}>
              <span>{period}</span>
              <i style={{ width: (n / maximum) * 100 + '%' }} />
              <b>{number(n)}</b>
            </div>
          ))}
        </div>
      ) : (
        <p>Sem registros no período.</p>
      )}
    </details>
  )
}
function Chat({ thread, onDraft, onAsk, onOpen, provider }) {
  const tail = useRef(null)
  useEffect(() => {
    if (thread.turns.length) tail.current?.scrollIntoView({ block: 'nearest' })
  }, [thread.turns.length])
  return (
    <section className="rw-card rw-chat">
      <div className="rw-heading">
        <h2>Conversa sobre o recorte</h2>
        <small>{provider === 'openai' ? 'IA generativa habilitada' : 'Consulta direta ao acervo'}</small>
      </div>
      <p className="rw-note">
        A conversa acompanha os filtros aplicados. Abra as referências para conferir o texto original.
      </p>
      {!thread.turns.length && (
        <div className="rw-prompts">
          {prompts.map((q) => (
            <button key={q} disabled={thread.busy} onClick={() => onAsk(q)}>
              {q}
            </button>
          ))}
        </div>
      )}
      {thread.turns.map((t, i) => (
        <article className="rw-turn" key={i}>
          <p className="rw-question">
            <strong>Você</strong>
            {t.question}
          </p>
          <small>{t.mode === 'openai' ? 'DatumLex · IA generativa' : 'DatumLex · Consulta ao acervo'}</small>
          {t.notice && <p>{t.notice}</p>}
          <Paragraphs blocks={t.paragraphs} docs={t.sources} onOpen={onOpen} />
        </article>
      ))}
      <div ref={tail} />
      <form
        className="rw-compose"
        onSubmit={(e) => {
          e.preventDefault()
          onAsk(thread.draft)
        }}
      >
        <label htmlFor="rw-question">Sua pergunta</label>
        <textarea
          id="rw-question"
          rows="2"
          maxLength="1200"
          disabled={thread.busy}
          value={thread.draft}
          onChange={(e) => onDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              if (!thread.busy && thread.draft.trim()) e.currentTarget.form.requestSubmit()
            }
          }}
          placeholder="Pergunte sobre um indicador, tema ou fonte…"
        />
        <div className="rw-actions">
          <button className="apply-button" disabled={thread.busy || !thread.draft.trim()}>
            <Send size={15} /> Enviar pergunta
          </button>
          <span role="status">{thread.busy ? 'Consultando a pesquisa…' : ''}</span>
        </div>
        {thread.error && <p role="alert">{thread.error}</p>}
      </form>
    </section>
  )
}

export default function ResearchWorkspace({ session }) {
  const [page, setPage] = useState('search'),
    [filters, setFilters] = useState(() => defaults(session.courts))
  const [drawer, setDrawer] = useState(null),
    [saved, setSaved] = useState({}),
    [threads, setThreads] = useState({})
  const [request, setRequest] = useState({}),
    [retry, setRetry] = useState(0),
    [subjects, setSubjects] = useState({})
  const [catalogCategory, setCatalogCategory] = useState(''),
    [exportError, setExportError] = useState('')
  const live = useRef(new Map())
  const params = pack(filters),
    key = new URLSearchParams(params).toString()
  const resource = page === 'precedents' ? 'research' : 'research/overview'
  const requestKey = resource + '?' + key
  const data = request.key === requestKey ? request.data : null,
    error = request.key === requestKey ? request.error : ''
  const thread = threads[key] || emptyThread
  const navRef = useRef(null)
  useEffect(() => {
    const pending = live.current
    return () => {
      for (const c of pending.values()) c.abort()
      pending.clear()
    }
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    getData(resource, Object.fromEntries(new URLSearchParams(key)), controller.signal)
      .catch((err) => {
        // Frontend and API roll out independently; support the previous API
        // during the short window before the new endpoint becomes available.
        if (resource === 'research/overview' && err.status === 404)
          return getData('research', Object.fromEntries(new URLSearchParams(key)), controller.signal)
        throw err
      })
      .then((data) => {
        if (!controller.signal.aborted) setRequest({ key: requestKey, data })
      })
      .catch((err) => {
        if (!controller.signal.aborted) setRequest({ key: requestKey, error: err.message })
      })
    return () => controller.abort()
  }, [key, resource, requestKey, retry])
  const courtParam = params.court
  useEffect(() => {
    const c = new AbortController()
    setSubjects({})
    getData('scope', { court: courtParam }, c.signal)
      .then((r) => {
        if (!c.signal.aborted)
          setSubjects(
            Object.fromEntries((r.subject_groups || r.subjects || []).map((s) => [
              String(s.code), s.name + ' (' + (s.codes || [s.code]).join(', ') + ')',
            ])),
          )
      })
      .catch(() => {})
    return () => c.abort()
  }, [courtParam])
  function navigate(id) {
    setPage(id)
    setExportError('')
    navRef.current?.focus({ preventScroll: true })
    window.scrollTo(0, 0)
  }
  function updateThread(fn) {
    setThreads((all) => ({ ...all, [key]: fn(all[key] || emptyThread) }))
  }
  function open(doc) {
    setDrawer({ doc })
  }
  async function ask(raw) {
    const q = raw.trim()
    if (!q || !data || live.current.has(key)) return
    const c = new AbortController()
    live.current.set(key, c)
    updateThread((t) => ({ ...t, busy: true, error: '', draft: q }))
    try {
      const csrf = await fetch(api + '/auth/csrf/', { credentials: 'include', signal: c.signal })
      if (!csrf.ok) throw Error('Falha ao iniciar a sessão do chat.')
      const { csrfToken } = await csrf.json()
      const resp = await fetch(api + '/research/chat/?' + key, {
        method: 'POST',
        credentials: 'include',
        signal: c.signal,
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify({
          question: q,
          previous: thread.turns
            .slice(-4)
            .map((turn) =>
              [turn.question, ...turn.sources.map((source) => source.id)].join(' ').slice(0, 1200),
            ),
        }),
      })
      if (resp.status === 401) window.dispatchEvent(new Event('datumlex:session-ended'))
      const answer = await resp.json()
      if (!resp.ok) throw Error(answer.error?.message || 'Falha na consulta.')
      if (!c.signal.aborted)
        updateThread((t) => ({
          ...t,
          busy: false,
          draft: '',
          turns: [...t.turns, { question: q, ...answer }],
        }))
    } catch (err) {
      if (!c.signal.aborted)
        updateThread((t) => ({ ...t, busy: false, error: err.message || 'Falha de conexão.' }))
    } finally {
      live.current.delete(key)
    }
  }
  async function exportReport(format) {
    setExportError('')
    try {
      const r = await fetch(api + '/research/export/?' + key + '&format=' + format, {
        credentials: 'include',
      })
      if (r.status === 401) window.dispatchEvent(new Event('datumlex:session-ended'))
      if (!r.ok) throw Error('Não foi possível exportar este recorte.')
      const url = URL.createObjectURL(await r.blob()),
        a = document.createElement('a')
      a.href = url
      a.download = 'datumlex-pesquisa-' + filters.end + '.' + format
      a.click()
      setTimeout(() => URL.revokeObjectURL(url), 10000)
      setDrawer(null)
    } catch (err) {
      setExportError(err.message)
    }
  }
  const selected = drawer?.doc,
    docs = data?.sources || [],
    m = data?.metrics
  const showFilters = page !== 'notebook' && page !== 'legacy'
  const railItems = Object.entries(pages)
  return (
    <div className="rw-shell">
      <aside className="rw-rail">
        <div className="rw-rail-title">Pesquisa jurídica</div>
        <nav aria-label="Seções da pesquisa">
          {railItems.map(([id, [label, , Icon]]) => (
            <button key={id} aria-current={id === page ? 'page' : undefined} onClick={() => navigate(id)}>
              <Icon size={17} />
              {label}
            </button>
          ))}
        </nav>
      </aside>
      <main className="rw-main" ref={navRef} tabIndex={-1}>
        <div className="rw-crumb">
          DatumLex <span>/</span> {pages[page][0]}
        </div>
        <div className="rw-heading">
          <div>
            <div className="eyebrow">Responsabilidade civil</div>
            <h1>{pages[page][1]}</h1>
          </div>
          {showFilters && (
            <button
              className="secondary-button"
              disabled={!data}
              onClick={() => setDrawer({ type: 'export' })}
            >
              <Download size={16} /> Exportar
            </button>
          )}
        </div>
        {showFilters && (
          <div className="rw-filterbar">
            <span>
              <small>Tribunais</small>
              {filters.court.length > 3 ? filters.court.length + ' tribunais' : filters.court.join(' + ')}
            </span>
            <span>
              <small>Temas do acervo</small>
              {filters.topics.map((k) => data?.topics?.[k] || k).join(', ') || 'Todos os temas'}
            </span>
            <span>
              <small>Período</small>
              {date(filters.start)} – {date(filters.end)}
            </span>
            <button className="secondary-button" onClick={() => setDrawer({ type: 'filter' })}>
              <SlidersHorizontal size={16} /> Filtros
            </button>
          </div>
        )}
        {page === 'legacy' ? (
          <>
            <p className="rw-note">
              Análise detalhada com filtros próprios, exportações completas e revisão das teses.
            </p>
            <App courts={session.courts} court={filters.court[0]} initialSelection={filters} />
          </>
        ) : page === 'notebook' ? (
          <section className="rw-card">
            <h2>Fontes guardadas nesta sessão</h2>
            {Object.values(saved).length ? (
              Object.values(saved).map((d) => <SourceRow key={d.id} doc={d} onOpen={open} />)
            ) : (
              <p>Abra uma fonte e escolha “Guardar no caderno”.</p>
            )}
          </section>
        ) : !data && page !== 'corpus' ? (
          <div className="rw-card" role={error ? 'alert' : 'status'}>
            {error || 'Consultando a base do DatumLex…'}{' '}
            {error && (
              <button
                className="secondary-button"
                onClick={() => {
                  setRequest({})
                  setRetry((n) => n + 1)
                }}
              >
                Tentar novamente
              </button>
            )}
          </div>
        ) : page === 'search' ? (
          <>
            <div className="rw-grid">
              <article className="rw-card rw-synthesis">
                <div className="rw-heading">
                  <h2>Síntese da pesquisa</h2>
                  <Sparkles size={18} />
                </div>
                <Paragraphs blocks={data.summary} docs={docs} onOpen={open} />
                {data.provider === 'openai' && (
                  <button
                    onClick={() => {
                      navigate('chat')
                      ask('Gere uma síntese dos indicadores, dos precedentes e da doutrina deste recorte.')
                    }}
                  >
                    <Sparkles size={16} /> Interpretar com IA
                  </button>
                )}{' '}
                <button onClick={() => navigate('chat')}>
                  <MessageSquare size={16} /> Conversar sobre a pesquisa
                </button>
              </article>
              <aside className="rw-card">
                <div className="rw-heading">
                  <h2>Fontes da pesquisa</h2>
                  <button className="rw-link" onClick={() => navigate('corpus')}>
                    Ver acervo
                  </button>
                </div>
                {['precedent', 'doctrine', 'jurisprudence'].map((k) => {
                  const d = docs.find((s) => s.kind === k)
                  return d ? (
                    <SourceRow key={k} doc={d} onOpen={open} />
                  ) : (
                    <p className="rw-note" key={k}>
                      {kinds[k]} · sem fonte neste recorte.
                    </p>
                  )
                })}
              </aside>
            </div>
            <div className="rw-metrics">
              {[
                ['Registros DataJud', number(m.process_records)],
                ['Resultados elegíveis', number(m.binary_denominator)],
                ['Taxa de provimento', rate(m.grant_rate)],
              ].map(([l, v]) => (
                <article className="rw-card" key={l}>
                  <small>{l}</small>
                  <strong>{v}</strong>
                </article>
              ))}
            </div>
            <History series={data.history} />
          </>
        ) : page === 'chat' ? (
          <Chat
            {...{ thread, provider: data.provider }}
            onOpen={open}
            onDraft={(draft) => updateThread((t) => ({ ...t, draft }))}
            onAsk={ask}
          />
        ) : page === 'corpus' ? (
          <section className="rw-card">
            <h2>Fontes do recorte</h2>
            <div className="rw-actions">
              {['', ...Object.keys(kinds).filter((k) => k !== 'link')].map((k) => (
                <button
                  className="secondary-button"
                  key={k}
                  aria-pressed={catalogCategory === k}
                  onClick={() => setCatalogCategory(k)}
                >
                  {sourceLabels[k] || 'Todas'}
                </button>
              ))}
            </div>
            <CorpusBrowser
              key={key + catalogCategory}
              scopeKey={key}
              category={catalogCategory}
              onOpen={open}
            />
          </section>
        ) : page === 'precedents' ? (
          <section className="rw-card">
            <h2>Uso de precedentes nas ementas</h2>
            <p className="rw-note">
              O NLP distingue aplicação, afastamento, menção e linguagem ambígua nas ementas verificadas. A
              bibliografia do acervo é agrupada por tema.
            </p>
            {data.usage ? (
              <div className="rw-metrics">
                {Object.entries({
                  applied: 'Aplicações',
                  not_applied: 'Afastamentos',
                  mentioned: 'Menções',
                  ambiguous: 'Ambíguos',
                }).map(([k, l]) => (
                  <div key={k}>
                    <small>{l}</small>
                    <strong>{number(data.usage[k])}</strong>
                  </div>
                ))}
              </div>
            ) : (
              <p>Selecione decisões e precedentes nos filtros para analisar os vínculos.</p>
            )}
            {docs
              .filter((d) => ['link', 'precedent'].includes(d.kind))
              .map((d) => (
                <SourceRow key={d.id} doc={d} onOpen={open} />
              ))}
            {!docs.some((d) => ['link', 'precedent'].includes(d.kind)) && (
              <p>Sem precedentes ou vínculos disponíveis no recorte.</p>
            )}
          </section>
        ) : (
          <section className="rw-card">
            <h2>O que cada fonte cobre</h2>
            {Object.entries(data.counts).map(([k, n]) => (
              <p key={k}>
                <strong>{sourceLabels[k]}</strong> · {number(n)} documentos indexados neste recorte.
              </p>
            ))}
            <p>
              Os indicadores DataJud usam a data de ajuizamento, o assunto CNJ e os resultados selecionados. O
              acervo usa os temas e a data de julgamento ou publicação. A doutrina é compartilhada entre os
              tribunais. Os vínculos em ementas usam tribunal, período, temas e assuntos CNJ confirmados.
            </p>
            <p>As taxas descrevem apenas os documentos carregados na base.</p>
          </section>
        )}
      </main>
      {drawer && (
        <Drawer
          title={
            selected?.title || { filter: 'Filtros da pesquisa', export: 'Exportar pesquisa' }[drawer.type]
          }
          onClose={() => setDrawer(null)}
        >
          {selected ? (
            <>
              <p>
                {kinds[selected.kind]} · {selected.origin} · {date(selected.date)}
              </p>
              {selected.authors?.length > 0 && <p>{selected.authors.join(', ')}</p>}
              <blockquote>
                {selected.excerpt || 'O índice contém a referência bibliográfica, sem trecho disponível.'}
              </blockquote>
              {selected.relation && <p>Classificação do NLP: {selected.relation}.</p>}
              <div className="rw-actions">
                {selected.url && (
                  <a className="rw-link" href={selected.url} target="_blank" rel="noreferrer">
                    Abrir publicação original
                  </a>
                )}
                <button
                  className="secondary-button"
                  onClick={() =>
                    setSaved((current) => {
                      const next = { ...current }
                      if (next[selected.id]) delete next[selected.id]
                      else next[selected.id] = selected
                      return next
                    })
                  }
                >
                  {saved[selected.id] ? 'Retirar do caderno' : 'Guardar no caderno'}
                </button>
              </div>
            </>
          ) : drawer.type === 'filter' ? (
            <Filters
              applied={filters}
              courts={session.courts}
              topics={data?.topics || request.data?.topics || {}}
              subjects={subjects}
              onApply={setFilters}
              onClose={() => setDrawer(null)}
            />
          ) : (
            <>
              <p>Baixe a síntese, o recorte aplicado e os trechos usados na pesquisa.</p>
              <div className="rw-actions">
                {['pdf', 'xlsx'].map((f) => (
                  <button className="secondary-button" key={f} onClick={() => exportReport(f)}>
                    {f === 'pdf' ? 'Baixar PDF' : 'Baixar Excel'}
                  </button>
                ))}
              </div>
              {exportError && <p role="alert">{exportError}</p>}
            </>
          )}
        </Drawer>
      )}
    </div>
  )
}

function CorpusBrowser({ scopeKey, category, onOpen }) {
  const [q, setQ] = useState(''),
    [term, setTerm] = useState(''),
    [page, setPage] = useState(1),
    [result, setResult] = useState({})
  const query = new URLSearchParams(scopeKey)
  query.set('category', category)
  query.set('q', term)
  query.set('page', String(page))
  const key = query.toString()
  useEffect(() => {
    const c = new AbortController()
    getData('research/sources', Object.fromEntries(new URLSearchParams(key)), c.signal)
      .then((data) => {
        if (!c.signal.aborted) setResult({ key, data })
      })
      .catch((e) => {
        if (!c.signal.aborted) setResult({ key, error: e.message })
      })
    return () => c.abort()
  }, [key])
  const data = result.key === key ? result.data : null
  return (
    <>
      <form
        className="rw-actions"
        onSubmit={(e) => {
          e.preventDefault()
          setPage(1)
          setTerm(q.trim())
        }}
      >
        <label>
          Buscar no título{' '}
          <input type="search" maxLength={120} value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <button className="secondary-button">Buscar</button>
      </form>
      {data ? (
        <>
          <p>{number(data.total)} documentos</p>
          {data.items.map((d) => (
            <SourceRow key={d.id} doc={d} onOpen={onOpen} />
          ))}
          <div className="rw-actions">
            <button className="secondary-button" disabled={page <= 1} onClick={() => setPage((n) => n - 1)}>
              Anterior
            </button>
            <span>Página {page}</span>
            <button
              className="secondary-button"
              disabled={page * 12 >= data.total}
              onClick={() => setPage((n) => n + 1)}
            >
              Próxima
            </button>
          </div>
        </>
      ) : (
        <p role="status">{(result.key === key && result.error) || 'Consultando documentos…'}</p>
      )}
    </>
  )
}
