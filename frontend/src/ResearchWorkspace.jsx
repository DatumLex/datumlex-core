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
import { formatProcessIdentifier } from './processIdentifier'
import {
  bibliographyLine,
  dateDisplay,
  publisherLine,
  rowSubtitle,
  sourceKindLabel,
  tpuDisplay,
} from './sourcePresentation'
import './research.css'

const api = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')
const pages = {
  search: ['Pesquisa', 'Pesquisa processual', Search],
  chat: ['Chat da pesquisa', 'Chat da pesquisa', MessageSquare],
  corpus: ['Acervo por assunto', 'Acervo por assunto', BookOpen],
  precedents: ['Precedentes e teses', 'Precedentes e teses', Scale],
  notebook: ['Caderno', 'Caderno de pesquisa', Bookmark],
  coverage: ['Fontes e cobertura', 'Fontes e cobertura', Database],
  legacy: ['Análise detalhada', 'Análise detalhada', FolderSearch],
}
const sourceLabels = {
  datajud: 'DataJud',
  jurisprudence: 'Jurisprudência',
  precedent: 'Precedentes',
  doctrine: 'Doutrina',
}
const kinds = {
  jurisprudence: 'Decisão',
  precedent: 'Precedente',
  doctrine: 'Doutrina',
  link: 'Vínculo em ementa',
}
const legalStatus = {
  consta_na_base_oficial: 'Consta na base oficial de súmulas',
  transito_em_julgado: 'Trânsito em julgado',
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
const degrees = { G1: '1ª instância', G2: '2ª instância', JE: 'Juizados especiais', TR: 'Turmas recursais', SUP: 'Tribunal superior' }
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
  cnj: '',
  topics: [],
  subject: ['10431'],
  sources: Object.keys(sourceLabels),
  outcomes: Object.keys(results),
  degree: [],
  start: '2010-01-01',
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
    <fieldset className={name === 'subject' ? 'rw-subject-options' : undefined}>
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
  const [tpuSearch, setTpuSearch] = useState('')
  const normalize = (value) => value.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase()
  const subjectOptions = Object.fromEntries(Object.entries(subjects).filter(([code, name]) =>
    draft.subject.includes(code) || normalize(name).includes(normalize(tpuSearch.trim()))
  ))
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
              min="2010-01-01"
              max={today()}
              value={draft[k]}
              onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
            />
          </label>
        ))}
      </div>
      <Choice name="degree" title="Grau DataJud (sem seleção: todos)" options={degrees} {...{ draft, setDraft }} />
      <label className="rw-tpu-search">
        Localizar assunto TPU
        <input type="search" value={tpuSearch} onChange={(e) => setTpuSearch(e.target.value)} placeholder="Nome ou código" />
      </label>
      <p className="rw-note">O assunto-pai abrange os descendentes. Os ramos selecionados entram por união, contando cada documento uma vez.</p>
      {draft.subject.includes('10431') && draft.subject.length > 1 && (
        <p className="rw-note">Para restringir a consulta aos subassuntos escolhidos, desmarque o assunto-pai 10431.</p>
      )}
      <Choice name="subject" title="Assuntos CNJ dos processos (TPU)" options={subjectOptions} {...{ draft, setDraft }} />
      {Object.keys(subjects).length > 0 && Object.keys(subjectOptions).length === 0 && <p>Nenhum assunto encontrado.</p>}
      <details>
        <summary>Resultados do DataJud</summary>
        <Choice name="outcomes" title="Classificação do resultado" options={results} {...{ draft, setDraft }} />
        <p className="rw-note">A seleção muda os documentos exibidos. A base da taxa é calculada antes deste filtro.</p>
      </details>
      <Choice name="topics" title="Temas do acervo e das ementas" options={topics} {...{ draft, setDraft }} />
      <p className="rw-note">Os temas editoriais filtram fontes e vínculos em ementas. Para restringir processos DataJud, use os assuntos CNJ.</p>
      {draft.topics.includes('transito') && <p className="rw-note">Trânsito na TPU · 10435 (dano moral) e 10441 (dano material).</p>}
      {draft.topics.includes('saude') && <p className="rw-note">Serviços de saúde na TPU · 10434 (dano moral) e 10440 (dano material). Erro Médico (40) é um assunto distinto, disponível na Análise detalhada.</p>}
      <Choice name="sources" title="Coleções na pesquisa" options={sourceLabels} {...{ draft, setDraft }} />
      <label>
        <input
          type="checkbox"
          checked={draft.undated}
          onChange={(e) => setDraft({ ...draft, undated: e.target.checked })}
        />{' '}
        Incluir fontes do acervo sem data
      </label>
      {error && <p role="alert">{error}</p>}
      <div className="rw-actions rw-filter-actions">
        <button type="submit" className="apply-button">
          Aplicar filtros
        </button>
        <button type="button" className="secondary-button" onClick={() => setDraft({ ...defaults(courts), cnj: applied.cnj })}>
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
        <small>{rowSubtitle(doc)}</small>
        <strong>{doc.title}</strong>
        {doc.authors?.length > 0 && <small>{doc.authors.join(', ')}</small>}
        {doc.topics?.length > 0 && <small>{doc.topics.join(' · ')}</small>}
        {doc.relation && <small>Candidato NLP · {doc.relation}</small>}
        {doc.review_status === 'pending' && <small>Revisão pendente</small>}
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
  const [useGemini, setUseGemini] = useState(false)
  const tail = useRef(null)
  useEffect(() => {
    if (thread.turns.length) tail.current?.scrollIntoView({ block: 'nearest' })
  }, [thread.turns.length])
  return (
    <section className="rw-card rw-chat">
      <div className="rw-heading">
        <h2>Conversa sobre o recorte</h2>
        <small>{provider === 'gemini' ? 'Gemini disponível' : 'Consulta direta ao acervo'}</small>
      </div>
      <p className="rw-note">
        A conversa acompanha os filtros aplicados. Abra as referências para conferir o texto original.
      </p>
      {!thread.turns.length && (
        <div className="rw-prompts">
          {prompts.map((q) => (
            <button key={q} disabled={thread.busy} onClick={() => onAsk(q, useGemini)}>
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
          <small>{t.mode === 'gemini' ? 'DatumLex · Seleção de achados com Gemini' : 'DatumLex · Consulta ao acervo'}</small>
          {t.notice && <p>{t.notice}</p>}
          <Paragraphs blocks={t.paragraphs} docs={t.sources} onOpen={onOpen} />
        </article>
      ))}
      <div ref={tail} />
      <form
        className="rw-compose"
        onSubmit={(e) => {
          e.preventDefault()
          onAsk(thread.draft, useGemini)
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
        {provider === 'gemini' && (
          <label>
            <input type="checkbox" checked={useGemini} disabled={thread.busy}
              onChange={(event) => setUseGemini(event.target.checked)} />
            {' '}Usar Gemini para selecionar achados com dados agregados do recorte
          </label>
        )}
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
    [cnjDraft, setCnjDraft] = useState(''),
    [exportError, setExportError] = useState('')
  const live = useRef(new Map())
  const params = pack(filters),
    key = new URLSearchParams(params).toString()
  const data = request.key === key ? request.data : null,
    error = request.key === key ? request.error : ''
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
    getData('research', Object.fromEntries(new URLSearchParams(key)), controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setRequest({ key, data })
      })
      .catch((err) => {
        if (!controller.signal.aborted) setRequest({ key, error: err.message })
      })
    return () => controller.abort()
  }, [key, retry])
  const { court: courtParam, start: startParam, end: endParam } = params
  useEffect(() => {
    const c = new AbortController()
    setSubjects({})
    getData('scope', { court: courtParam, start: startParam, end: endParam }, c.signal)
      .then((r) => {
        if (!c.signal.aborted) {
          const tree = Object.fromEntries((r.civil_subjects || []).map((item) => [item.code, item]))
          setSubjects(Object.fromEntries(Object.values(tree).map((item) => [
            String(item.code),
            [tree[item.parent]?.name, item.name].filter(Boolean).join(' › ')
              + ' (' + item.code + ' · ' + number(item.record_count) + ' registros)',
          ])))
        }
      })
      .catch(() => {})
    return () => c.abort()
  }, [courtParam, startParam, endParam])
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
  async function ask(raw, useGemini = false) {
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
          use_gemini: useGemini,
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
  async function exportReport(format, content = 'summary') {
    setExportError('')
    try {
      const r = await fetch(api + '/research/export/?' + key + '&format=' + format + '&content=' + content, {
        credentials: 'include',
      })
      if (r.status === 401) window.dispatchEvent(new Event('datumlex:session-ended'))
      if (!r.ok) throw Error('Não foi possível exportar este recorte.')
      const url = URL.createObjectURL(await r.blob()),
        a = document.createElement('a')
      a.href = url
      a.download = 'datumlex-' + (content === 'records' ? 'registros-datajud' : 'sintese') + '-' + filters.end + '.' + format
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
        <div className="rw-mobile-nav">
          <label htmlFor="rw-section">Seção</label>
          <select id="rw-section" value={page} onChange={(e) => navigate(e.target.value)}>
            {railItems.map(([id, [label]]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </div>
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
        {page === 'search' && (
          <form className="rw-actions rw-query" onSubmit={(event) => {
            event.preventDefault()
            setFilters({ ...filters, cnj: cnjDraft.trim().replace(/[.-]/g, '') })
          }}>
            <label>
              Número CNJ exato
              <input type="search" inputMode="numeric" maxLength={25} value={cnjDraft}
                pattern="[0-9]{20}|[0-9]{7}-[0-9]{2}[.][0-9]{4}[.][0-9][.][0-9]{2}[.][0-9]{4}"
                placeholder="Com ou sem pontuação" onChange={(event) => setCnjDraft(event.target.value)} />
            </label>
            <button className="secondary-button">Consultar processo</button>
            {filters.cnj && <button type="button" className="rw-link" onClick={() => {
              setCnjDraft('')
              setFilters({ ...filters, cnj: '' })
            }}>Limpar número CNJ</button>}
            <button type="button" className="rw-link" onClick={() => {
              setCatalogCategory('precedent')
              navigate('corpus')
            }}>Buscar precedentes</button>
          </form>
        )}
        {showFilters && (
          <div className="rw-filterbar">
            <span>
              <small>Tribunais</small>
              {filters.court.length > 3 ? filters.court.length + ' tribunais' : filters.court.join(' + ')}
            </span>
            <span>
              <small>Temas do acervo e ementas</small>
              {filters.topics.map((k) => data?.topics?.[k] || k).join(', ') || 'Todos os temas'}
            </span>
            <span>
              <small>{page === 'corpus' ? 'Julgamento ou publicação' : 'Período solicitado'}</small>
              {date(filters.start)} – {date(filters.end)}
            </span>
            {page !== 'corpus' && <span>
              <small>Assuntos CNJ ativos (TPU)</small>
              <strong>{[...filters.subject].sort().join(', ') || 'Todos no lote'}</strong>
            </span>}
            {page !== 'corpus' && filters.cnj && <span><small>CNJ consultado</small>{formatProcessIdentifier(filters.cnj)}</span>}
            {page !== 'corpus' && filters.outcomes.length !== Object.keys(results).length &&
              <span><small>Resultados DataJud exibidos</small>{filters.outcomes.map((key) => results[key]).join(', ')}</span>}
            {filters.degree.length > 0 && page !== 'corpus' && <span><small>Grau DataJud</small>{filters.degree.map((key) => degrees[key]).join(', ')}</span>}
            <button className="secondary-button" onClick={() => setDrawer({ type: 'filter' })}>
              <SlidersHorizontal size={16} /> Filtros
            </button>
          </div>
        )}
        {page === 'legacy' ? (
          <>
            <p className="rw-note">
              A Análise detalhada usa seu próprio recorte e agrega os tribunais selecionados.
              Um assunto CNJ corresponde ao código escolhido e aos códigos de mesmo nome.
              Na Pesquisa, selecionar 10431 inclui toda a hierarquia de Responsabilidade Civil.
              Ao abrir a análise, são trazidos tribunais, período e, se houver, um único código TPU.
              Busca por CNJ, grau, múltiplos códigos e resultado ficam na Pesquisa.
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
        ) : !data ? (
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
            <section className="rw-card rw-results" aria-labelledby="rw-process-title">
              <div className="rw-heading">
                <h2 id="rw-process-title">Resultados processuais</h2>
                <button className="rw-link" onClick={() => navigate('coverage')}>Ver cobertura do lote</button>
              </div>
              <p><strong>{number(m.process_records)} documentos DataJud</strong> · {number(m.distinct_process_numbers)} números CNJ distintos.</p>
              <p className="rw-note">Processos por data de ajuizamento. O assunto-pai inclui descendentes e a união dos códigos conta cada documento uma vez.</p>
              <p className="rw-note">Temas editoriais atuam no acervo e nas ementas. A lista processual mantém o recorte TPU aplicado.</p>
              {data.scope.sources.includes('datajud') ? <CaseBrowser key={key} scopeKey={key} /> : <p>DataJud desmarcado nos filtros.</p>}
            </section>
            <div className="rw-grid">
              <article className="rw-card rw-synthesis">
                <div className="rw-heading">
                  <h2>Síntese da pesquisa</h2>
                  <Sparkles size={18} />
                </div>
                <Paragraphs blocks={data.summary.slice(0, 2)} docs={docs} onOpen={open} />
                {data.summary.length > 2 && <details>
                  <summary>Ver síntese completa</summary>
                  <Paragraphs blocks={data.summary.slice(2)} docs={docs} onOpen={open} />
                </details>}
                {data.provider === 'gemini' && (
                  <button
                    onClick={() => navigate('chat')}
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

                </div>
                {['jurisprudence', 'precedent', 'doctrine'].map((kind) => (
                  <div className="rw-catalog-shortcut" key={kind}>
                    <button className="rw-link" onClick={() => {
                      setCatalogCategory(kind)
                      navigate('corpus')
                    }}>{sourceLabels[kind]}</button>
                    <span>{data.scope.sources.includes(kind) ? `${number(data.counts[kind])} fontes aprovadas` : 'Fora do recorte'}</span>
                  </div>
                ))}
              </aside>
            </div>
            {data.scope.sources.includes('datajud') && <ResearchIndicators data={data} />}
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
            <h2>Fontes aprovadas do recorte</h2>
            <p>Tribunal, julgamento ou publicação, tema editorial e tipo de fonte definem este acervo.
              A doutrina é compartilhada. Grau e número CNJ da Pesquisa filtram a lista processual.</p>
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
            <h2>Precedentes aprovados</h2>
            <button className="rw-link" onClick={() => {
              setCatalogCategory('precedent')
              navigate('corpus')
            }}>Consultar precedentes no acervo</button>
            {!docs.some((d) => ['link', 'precedent'].includes(d.kind)) && (
              <p>Sem precedentes ou vínculos disponíveis no recorte.</p>
            )}
            <h3>Uso de precedentes nas ementas</h3>
            <p className="rw-note">
              O NLP distingue aplicação, afastamento, menção e linguagem ambígua nas ementas verificadas. A
              bibliografia do acervo é agrupada por tema.
            </p>
            {data.usage && Object.values(data.usage).some(Boolean) ? (
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
            ) : !data.usage && <p>Selecione jurisprudência e precedentes nos filtros para analisar os vínculos.</p>}
            {docs
              .filter((d) => ['link', 'precedent'].includes(d.kind))
              .map((d) => (
                <SourceRow key={d.id} doc={d} onOpen={open} />
              ))}
          </section>
        ) : (
          <section className="rw-card">
            <h2>O que cada fonte cobre</h2>
            <Coverage scopeKey={key} />
            {Object.entries(data.counts).map(([k, n]) => (
              <p key={k}>
                <strong>{sourceLabels[k]}</strong> · {number(n)} fontes aprovadas neste recorte.
              </p>
            ))}
            <p>
              Os indicadores DataJud usam a data de ajuizamento, o assunto CNJ e os resultados selecionados. O
              acervo usa os temas e a data de julgamento ou publicação. A doutrina é compartilhada entre os
              tribunais. Os vínculos em ementas usam tribunal, período, temas e assuntos CNJ confirmados.
            </p>
            <p>A taxa usa somente os resultados binários elegíveis da base anterior ao filtro de resultado.</p>
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
            <SourceDetail
              doc={selected}
              saved={Boolean(saved[selected.id])}
              onToggleSave={() =>
                setSaved((current) => {
                  const next = { ...current }
                  if (next[selected.id]) delete next[selected.id]
                  else next[selected.id] = selected
                  return next
                })
              }
            />
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
              <p>Síntese com filtros, indicadores e fontes citadas.</p>
              <div className="rw-actions">
                {['pdf', 'xlsx'].map((f) => (
                  <button className="secondary-button" key={f} onClick={() => exportReport(f)}>
                    {f === 'pdf' ? 'Síntese em PDF' : 'Síntese em Excel'}
                  </button>
                ))}
              </div>
              {data?.scope.sources.includes('datajud') && <>
                <p>Planilha com cada documento DataJud encontrado e os filtros da lista processual.</p>
                <button className="secondary-button" onClick={() => exportReport('xlsx', 'records')}>
                  Registros DataJud em Excel
                </button>
              </>}
              {exportError && <p role="alert">{exportError}</p>}
            </>
          )}
        </Drawer>
      )}
    </div>
  )
}

function SourceDetail({ doc, saved, onToggleSave }) {
  const when = dateDisplay(doc)
  const bibLine = bibliographyLine(doc)
  const pubLine = publisherLine(doc)
  const tpu = tpuDisplay(doc)
  return (
    <>
      <p>
        {sourceKindLabel(doc)} · {doc.court || doc.origin}
        {doc.judging_body && ` · ${doc.judging_body}`}
      </p>
      {doc.authors?.length > 0 && <p>Autores · {doc.authors.join(', ')}</p>}
      {bibLine && <p>Publicação · {bibLine}</p>}
      {pubLine && <p>Instituição responsável · {pubLine}</p>}
      {when && <p>{when.label} · {when.value}</p>}
      {doc.identifier && <p>Identificador · {doc.identifier}</p>}
      {doc.case_number && <p>Processo · {formatProcessIdentifier(doc.case_number)}</p>}
      {doc.reference_number && <p>Referência · {doc.reference_number}</p>}
      {legalStatus[doc.official_status] && <p>Situação oficial · {legalStatus[doc.official_status]}</p>}
      {doc.verified_on && <p>Conferida em {date(doc.verified_on)}</p>}
      {tpu && <p>{tpu.label} · {tpu.codes}</p>}
      {doc.license?.name && (
        <>
          <p>
            Licença ·{' '}
            {doc.license.url ? (
              <a className="rw-link" href={doc.license.url} target="_blank" rel="noreferrer">
                {doc.license.name}
              </a>
            ) : (
              doc.license.name
            )}
          </p>
          {doc.license.attribution && <p>Atribuição · {doc.license.attribution}</p>}
          {doc.license.version_note && <p className="rw-note">{doc.license.version_note}</p>}
        </>
      )}
      {doc.topics?.length > 0 && (
        <p>
          Assuntos editoriais · {doc.topics.join(' · ')}. A associação indica afinidade temática e não comprova
          aplicação a um processo.
        </p>
      )}
      {doc.excerpt ? (
        <blockquote>{doc.excerpt}</blockquote>
      ) : (
        <p className="rw-note">
          A ficha exibe metadados e link. O texto da fonte está disponível apenas na publicação de origem.
        </p>
      )}
      {doc.relation && <p>Classificação candidata do NLP: {doc.relation}.</p>}
      {doc.review_status === 'pending' && <p>Fonte com revisão pendente.</p>}
      <div className="rw-actions">
        {doc.url && (
          <a className="rw-link" href={doc.url} target="_blank" rel="noreferrer">
            Abrir publicação original
          </a>
        )}
        <button className="secondary-button" onClick={onToggleSave}>
          {saved ? 'Retirar do caderno' : 'Guardar no caderno'}
        </button>
      </div>
    </>
  )
}

function ResearchIndicators({ data }) {
  const base = data.merit_baseline
  const exclusions = Object.entries(base.excluded).filter(([, count]) => count > 0)
  const excluded = exclusions.reduce((total, [, count]) => total + count, 0)
  const hasOutcomeFilter = data.scope.outcomes.length !== Object.keys(results).length
  return (
    <section className="rw-card rw-indicators" aria-labelledby="rw-indicators-title">
      <h2 id="rw-indicators-title">Indicadores do recorte</h2>
      {base.binary_denominator > 0 ? (
        <p><strong>{number(base.granted)} de {number(base.binary_denominator)} providos ({rate(base.grant_rate)})</strong>
          {' · '}{number(base.denied)} desprovidos.</p>
      ) : <p><strong>Sem documentos elegíveis para calcular a taxa.</strong></p>}
      <p>{number(base.binary_denominator)} documentos elegíveis para a taxa e {number(excluded)} excluídos da base binária.</p>
      {hasOutcomeFilter && <p>O filtro de resultado mostra {number(data.metrics.process_records)} documentos de {number(base.binary_denominator + excluded)}.
        O cálculo acima usa a base anterior a esse filtro.</p>}
      {exclusions.length > 0 && <details>
        <summary>Ver exclusões da base</summary>
        <ul>{exclusions.map(([key, count]) => <li key={key}>{results[key]} · {number(count)}</li>)}</ul>
      </details>}
      <p className="rw-note">Cobertura parcial. A regra de resultado recursal foi validada para TJDFT (2ª instância e turmas recursais) e STJ (grau superior). A taxa descreve a amostra e não estima a chance de êxito judicial.</p>
    </section>
  )
}

const coverageLabels = {
  target_met: 'Meta da amostra atingida',
  partial: 'Amostra parcial',
  failed: 'Coleta falha registrada',
  unverified: 'Sem registros no lote · cobertura não verificada',
}

function useScopedResult(resource, key) {
  const [result, setResult] = useState({})
  useEffect(() => {
    const controller = new AbortController()
    getData(resource, Object.fromEntries(new URLSearchParams(key)), controller.signal)
      .then((data) => { if (!controller.signal.aborted) setResult({ key, data }) })
      .catch((error) => { if (!controller.signal.aborted) setResult({ key, error: error.message }) })
    return () => controller.abort()
  }, [resource, key])
  return result.key === key ? result : {}
}

function Coverage({ scopeKey }) {
  const { data, error } = useScopedResult('research/coverage', scopeKey)
  if (!data) return <p role={error ? 'alert' : 'status'}>{error || 'Consultando a cobertura…'}</p>
  if (!data.coverage) return <p>Sem informação de cobertura por coorte.</p>
  const { cells, by_court, target_per_cell } = data.coverage
  return (
    <div>
      <h3>Cobertura observada no DataJud</h3>
      <p>{cells.filter((cell) => cell.members > 0).length} de {cells.length} células tribunal/ano com registros no lote.
        {' '}Meta de {target_per_cell} por célula, com {number(cells.reduce((gap, cell) => gap + Math.max(0, target_per_cell - cell.members), 0))} vagas remanescentes.
        {' '}O quadro anual considera tribunal e ano.</p>
      <p>A ausência de registros no lote não comprova zero processos no tribunal. O lote não certifica células vazias.</p>
      {[...new Set(cells.map((cell) => cell.court))].map((court) => (
        <details key={court}>
          <summary>{court} · {by_court[court] ? date(by_court[court].first) + ' a ' + date(by_court[court].last) : 'Sem registros no lote'}</summary>
          <ul>
            {cells.filter((cell) => cell.court === court).map((cell) => (
              <li key={cell.year}>{cell.year} · {coverageLabels[cell.state]}
                {cell.members > 0 && ` · ${number(cell.members)}/${target_per_cell} registros`}
                {cell.collection_failed && cell.state !== 'failed' && ' · coleta falha registrada'}
              </li>
            ))}
          </ul>
        </details>
      ))}
    </div>
  )
}

function CaseBrowser({ scopeKey }) {
  const [page, setPage] = useState(1)
  const { data, error } = useScopedResult('research/processes', scopeKey + '&page=' + page)
  if (!data) return <p role={error ? 'alert' : 'status'}>{error || 'Consultando processos…'}</p>
  if (!data.total) return <p>Nenhum documento DataJud corresponde aos filtros.</p>
  return (
    <>
      {data.items.map((item) => (
        <details className="rw-process-row" key={item.id}>
          <summary>
            <span>{formatProcessIdentifier(item.number)}</span>
            <small>{item.court} · {degrees[item.degree] || item.degree} · {results[item.outcome] || item.outcome}</small>
          </summary>
          <dl>
            <div><dt>Classe</dt><dd>{item.class_name || 'Não informada'}</dd></div>
            <div><dt>Órgão julgador</dt><dd>{item.organization || 'Não informado'}</dd></div>
            <div><dt>Ajuizamento</dt><dd>{date(item.filing)}</dd></div>
          </dl>
          <p className="rw-note">Origem DataJud/CNJ · resultado classificado a partir dos movimentos mapeados.</p>
        </details>
      ))}
      <div className="rw-actions">
        <button className="secondary-button" disabled={page === 1} onClick={() => setPage(page - 1)}>Anterior</button>
        <span>Página {page}</span>
        <button className="secondary-button" disabled={page * 12 >= data.total} onClick={() => setPage(page + 1)}>Próxima</button>
      </div>
    </>
  )
}

function CorpusBrowser({ scopeKey, category, onOpen }) {
  const [q, setQ] = useState(''),
    [search, setSearch] = useState({ term: '', allDates: false }),
    [allDates, setAllDates] = useState(true),
    [page, setPage] = useState(1),
    [result, setResult] = useState({})
  const query = new URLSearchParams(scopeKey)
  query.set('category', category)
  query.set('q', search.term)
  if (search.allDates) query.set('all_dates', 'true')
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
          const term = q.trim()
          setSearch({ term, allDates: category === 'precedent' && Boolean(term) && allDates })
        }}
      >
        <label>
          Título ou identificador{' '}
          <input type="search" maxLength={120} value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <button className="secondary-button">Buscar</button>
        {category === 'precedent' && <label>
          <input type="checkbox" checked={allDates} onChange={(e) => setAllDates(e.target.checked)} />
          {' '}Buscar precedentes em todas as datas
        </label>}
      </form>
      {search.allDates && <p className="rw-note">Busca por referência em todas as datas. Tribunal e temas selecionados continuam em vigor.</p>}
      {data ? (
        <>
          <p>{data.total ? `${number(data.total)} fontes aprovadas` : 'Nenhuma fonte aprovada neste recorte.'}</p>
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
