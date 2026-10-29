import { useEffect, useRef, useState } from 'react'
import { BarChart3, Info, X, ListChecks, ChevronDown } from 'lucide-react'
import { downloadReport, getData } from './api'
import NlpPanel from './NlpPanel'
import CorpusPanel from './CorpusPanel'
import SourceDecisions from './SourceDecisions'

const number = new Intl.NumberFormat('pt-BR')
const formatNumber = (value) => value == null ? '—' : number.format(value)
const formatRate = (value) => value == null ? '—' : new Intl.NumberFormat('pt-BR', { style: 'percent', maximumFractionDigits: 1 }).format(value)
const formatDate = (value) => value ? new Date(`${value}T12:00:00`).toLocaleDateString('pt-BR') : '—'
const supportedPeriod = () => ({ start: '2016-01-01', end: new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Sao_Paulo', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()) })
const shortThesisLabel = (thesis) => {
  const label = thesis.label || thesis.titulo || thesis.title || 'Tese sem título'
  return label.trim().split(/\s+/).slice(0, 4).join(' ')
}
const degrees = { G1: '1ª instância', G2: '2ª instância', JE: 'Juizados especiais', TR: 'Turmas recursais', SUP: 'Tribunal superior' }
const relationLabels = { aligned: 'Adesão identificada', divergent: 'Divergência sinalizada', distinguished: 'Distinção registrada', uncertain: 'Inconclusivo' }

function IndicatorCard({ label, value, accent, note }) {
  return <article className={`indicator-card indicator-card--${accent}`}>
    <strong>{value}</strong><p>{label}</p><small>{note}</small>
  </article>
}

function ChartCard({ title, description, children }) {
  return <section className="chart-card" aria-label={title}>
    <div className="chart-heading"><div><h2>{title}</h2><p>{description}</p></div><BarChart3 aria-hidden="true" size={24} /></div>
    {children}
  </section>
}

function ChartState({ title, children }) {
  return <div className="chart-empty"><div className="empty-chart-icon"><BarChart3 aria-hidden="true" size={30} /></div><strong>{title}</strong><p>{children}</p></div>
}

function EvidenceDrawer({ item, onClose }) {
  const drawerRef = useRef(null)
  useEffect(() => { if (item) drawerRef.current?.focus() }, [item])
  if (!item) return null
  const candidate = item.kind === 'candidate'
  const confidence = item.confidence == null
    ? 'Não informado pela API'
    : `${new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 }).format(Number(item.confidence) * 100)}%`
  const identifier = candidate ? item.reference_identifier : item.reference?.identifier
  const sourceUrl = candidate ? item.reference_url : item.reference?.source_url
  const title = candidate ? item.reference_title : item.reference?.title
  const sourceLocator = candidate ? item.source_locator : item.reference?.source_locator
  const excerpt = candidate ? null : item.evidence_excerpt

  return <div className="evidence-drawer-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <aside ref={drawerRef} tabIndex={-1} className="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="evidence-drawer-title" onKeyDown={(event) => { if (event.key === 'Escape') onClose() }}>
      <div className="evidence-drawer-heading"><div><span className="eyebrow">Fonte rastreável</span><h3 id="evidence-drawer-title">{title || identifier || 'Evidência'}</h3></div><button type="button" className="secondary-button" onClick={onClose} aria-label="Fechar fontes">Fechar</button></div>
      <dl className="evidence-drawer-fields">
        <div><dt>Identificador da fonte</dt><dd>{identifier || 'Não informado pela API'}</dd></div>
        <div><dt>Órgão</dt><dd>{candidate ? 'Não informado no item candidato' : item.reference?.source_institution || 'Não informado pela API'}</dd></div>
        <div><dt>Data da decisão</dt><dd>{candidate ? 'Não informada para esta sugestão' : formatDate(item.decision_date)}</dd></div>
        <div><dt>Nível de confiança</dt><dd>{confidence}</dd></div>
        <div><dt>Processo local</dt><dd>{item.local_process_number || 'Não informado pela API'}</dd></div>
        <div><dt>Localizador</dt><dd>{sourceLocator || 'Não informado pela API'}</dd></div>
      </dl>
      {excerpt ? <section className="evidence-drawer-excerpt"><h4>Trecho da decisão</h4><blockquote>{excerpt}</blockquote></section> : <section className="evidence-drawer-excerpt"><h4>{candidate ? 'Detalhes da associação' : 'Trecho da decisão'}</h4><p>{candidate ? item.explanation || 'A API não retornou detalhes para esta sugestão.' : 'A API não retornou trecho para esta avaliação.'}</p></section>}
      {!candidate && item.rationale && <section className="evidence-drawer-excerpt"><h4>Fundamentação da revisão</h4><p>{item.rationale}</p></section>}
      {candidate && <p className="evidence-drawer-note">Esta é uma sugestão de correspondência por identificador. Não representa avaliação de aderência jurídica.</p>}
      {sourceUrl && <a className="evidence-source-link" href={sourceUrl} target="_blank" rel="noreferrer">Abrir fonte original ↗</a>}
    </aside>
  </div>
}

const degreeColors = { G1: '#1f4e5f', G2: '#c9a227', JE: '#3f7452', TR: '#718496', SUP: '#866a96' }

function useChartTooltip() {
  const [tooltip, setTooltip] = useState(null)
  const showAtPointer = (event, key, text) => setTooltip({ key, text, x: event.clientX, y: event.clientY - 14 })
  const showAtElement = (event, key, text) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    setTooltip({ key, text, x: bounds.left + bounds.width / 2, y: bounds.top - 10 })
  }
  const hide = () => setTooltip(null)
  return { tooltip, showAtPointer, showAtElement, hide }
}

function ChartTooltip({ id, tooltip }) {
  if (!tooltip) return null
  return <div id={id} className="chart-tooltip" role="tooltip" style={{ left: tooltip.x, top: tooltip.y }}>{tooltip.text}</div>
}

function InstanceChart({ series }) {
  const { tooltip, showAtPointer, showAtElement, hide } = useChartTooltip()
  const tooltipId = 'instance-chart-tooltip'
  const groups = new Map()
  for (const row of series) {
    const key = row.time__year * 4 + row.time__quarter - 1
    if (!groups.has(key)) groups.set(key, {})
    groups.get(key)[row.degree] = (groups.get(key)[row.degree] || 0) + row.count
  }
  const keys = [...groups.keys()].sort((a, b) => a - b)
  const periods = Array.from({ length: keys.at(-1) - keys[0] + 1 }, (_, i) => {
    const key = keys[0] + i
    return { key, label: `T${key % 4 + 1}/${String(Math.floor(key / 4)).slice(-2)}`, values: groups.get(key) || {} }
  })
  const present = Object.keys(degrees).filter((degree) => series.some((row) => row.degree === degree))
  const maximum = Math.max(1, ...periods.map((period) => Object.values(period.values).reduce((a, b) => a + b, 0)))
  const step = Math.max(1, Math.ceil(maximum / 5))
  const ceiling = step * 5
  const width = Math.max(480, periods.length * 36 + 52)
  const plotWidth = width - 56
  const slot = plotWidth / periods.length
  return <>
    <div className="period-chart-scroll">
      <svg className="period-chart" viewBox={`0 0 ${width} 330`} style={{ minWidth: width }} role="img" aria-label="Barras empilhadas: documentos por trimestre de ajuizamento e instância">
        {Array.from({ length: 6 }, (_, i) => <g key={i}>
          <line x1="42" x2={width - 14} y1={272 - i * 48} y2={272 - i * 48} stroke="#e8e5dc" />
          <text x="34" y={276 - i * 48} textAnchor="end">{formatNumber(i * step)}</text>
        </g>)}
        {periods.map((period, index) => {
          let accumulated = 0
          return <g key={period.key}>{present.map((degree) => {
            const count = period.values[degree] || 0
            const height = count / ceiling * 240
            accumulated += height
            const segmentKey = `${period.key}-${degree}`
            const label = `${period.label} · ${degrees[degree]}: ${formatNumber(count)} documentos`
            return <rect className="chart-segment" key={degree} x={42 + index * slot + slot * .23} y={272 - accumulated} width={slot * .54} height={height} fill={degreeColors[degree]} tabIndex={count ? 0 : undefined} aria-label={label} aria-describedby={tooltip?.key === segmentKey ? tooltipId : undefined}
              onPointerEnter={(event) => showAtPointer(event, segmentKey, label)} onPointerMove={(event) => showAtPointer(event, segmentKey, label)} onPointerLeave={hide}
              onFocus={(event) => showAtElement(event, segmentKey, label)} onBlur={hide} onKeyDown={(event) => { if (event.key === 'Escape') hide() }} />
          })}<text x={42 + (index + .5) * slot} y="294" textAnchor="middle">{period.label}</text></g>
        })}
      </svg>
    </div>
    <ChartTooltip id={tooltipId} tooltip={tooltip} />
    <div className="chart-legend">{present.map((degree) => <span key={degree}><i style={{ background: degreeColors[degree] }} />{degree} — {degrees[degree]}</span>)}</div>
    <p className="chart-note">Compare o volume e a composição por instância ao longo do período. A data é de ajuizamento; as barras não representam a evolução de um mesmo processo.</p>
    <details className="chart-table"><summary>Ver dados por trimestre</summary><table>
      <caption>Documentos por trimestre de ajuizamento e instância</caption>
      <thead><tr><th scope="col">Trimestre</th>{present.map((degree) => <th scope="col" key={degree}>{degree}</th>)}</tr></thead>
      <tbody>{periods.map((period) => <tr key={period.key}><td>{period.label}</td>{present.map((degree) => <td key={degree}>{formatNumber(period.values[degree] || 0)}</td>)}</tr>)}</tbody>
    </table></details>
  </>
}

function OutcomeChart({ series }) {
  const { tooltip, showAtPointer, showAtElement, hide } = useChartTooltip()
  const tooltipId = 'outcome-chart-tooltip'
  const total = series.reduce((sum, row) => sum + row.count, 0)
  return <>
    <svg className="outcome-donut" viewBox="0 0 360 340" role="img" aria-label={`Proporção de resultados em ${formatNumber(total)} documentos`}>
      {series.map((row, index) => {
        const portion = total ? row.count / total * 100 : 0
        const start = total ? series.slice(0, index).reduce((sum, item) => sum + item.count, 0) / total * 100 : 0
        const label = row.outcome === 'granted' ? 'Providos' : 'Desprovidos'
        const text = `${label}: ${formatNumber(row.count)} (${formatRate(row.rate)})`
        return <circle className="chart-segment" key={row.outcome} cx="180" cy="170" r="124" pathLength="100" fill="none" stroke={row.outcome === 'granted' ? '#1f4e5f' : '#c9a227'} strokeWidth="62" strokeDasharray={`${portion} ${100 - portion}`} strokeDashoffset={-start} transform="rotate(-90 180 170)" tabIndex="0" aria-label={text} aria-describedby={tooltip?.key === row.outcome ? tooltipId : undefined}
          onPointerEnter={(event) => showAtPointer(event, row.outcome, text)} onPointerMove={(event) => showAtPointer(event, row.outcome, text)} onPointerLeave={hide}
          onFocus={(event) => showAtElement(event, row.outcome, text)} onBlur={hide} onKeyDown={(event) => { if (event.key === 'Escape') hide() }} />
      })}
      <text x="180" y="168" textAnchor="middle" className="donut-total">{formatNumber(total)}</text>
      <text x="180" y="193" textAnchor="middle" className="donut-caption">documentos com resultado</text>
    </svg>
    <ChartTooltip id={tooltipId} tooltip={tooltip} />
    <div className="chart-legend outcome-legend">{series.map((row) => <span key={row.outcome}><i style={{ background: row.outcome === 'granted' ? '#1f4e5f' : '#c9a227' }} /><span>{row.outcome === 'granted' ? 'Providos' : 'Desprovidos'}<strong>{formatRate(row.rate)} · {formatNumber(row.count)}</strong></span></span>)}</div>
  </>
}

export default function App({ court: initialCourt, courts: authorizedCourts }) {
  const [courts, setCourts] = useState(() => authorizedCourts.length ? [...authorizedCourts] : [initialCourt])
  const court = courts.join(',')
  const [courtMenuOpen, setCourtMenuOpen] = useState(false)
  const courtMenuRef = useRef(null)
  const courtButtonRef = useRef(null)
  useEffect(() => {
    if (!courtMenuOpen) return
    const closeOutside = (event) => {
      if (!courtMenuRef.current?.contains(event.target)) setCourtMenuOpen(false)
    }
    document.addEventListener('pointerdown', closeOutside)
    return () => document.removeEventListener('pointerdown', closeOutside)
  }, [courtMenuOpen])
  function selectCourts(next) {
    if (!next.length) return
    if (next.length === courts.length && next.every((code) => courts.includes(code))) return
    setCourts(next)
    setLoading(true); setError('')
  }
  const [isMethodologyOpen, setIsMethodologyOpen] = useState(false)
  const [activeTab, setActiveTab] = useState('corpus')
  const [draft, setDraft] = useState({ start: '', end: '', subject: '' })
  const [applied, setApplied] = useState(null)
  const bounds = supportedPeriod()
  const [data, setData] = useState(null)
  const [alignment, setAlignment] = useState(null)
  const [selectedThesisId, setSelectedThesisId] = useState(null)
  const [evidenceDrawerItem, setEvidenceDrawerItem] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [validation, setValidation] = useState('')
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState('')
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const refreshIfVisible = () => {
      if (document.visibilityState === 'visible') setRetry((value) => value + 1)
    }
    const interval = window.setInterval(refreshIfVisible, 5 * 60 * 1000)
    document.addEventListener('visibilitychange', refreshIfVisible)
    return () => {
      window.clearInterval(interval)
      document.removeEventListener('visibilitychange', refreshIfVisible)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    const timeout = setTimeout(() => controller.abort(), 20000)
    async function load() {
      try {
        setAlignment(null)
        setSelectedThesisId(null)
        setEvidenceDrawerItem(null)
        if (courts.some((code) => !authorizedCourts.includes(code))) throw new Error('Você não possui acesso a este tribunal.')
        const fullScope = await getData('scope', { court }, controller.signal)
        const courtScopes = { selection: fullScope }
        const available = supportedPeriod()
        const filters = applied || (available.start && available.end ? { start: available.start, end: available.end } : {})
        const [statistics, instances, distribution] = await Promise.all(
          ['statistics', 'instances', 'distribution'].map((resource) => getData(resource, { ...filters, court }, controller.signal)),
        )
        const filteredScope = await getData('scope', { ...filters, court }, controller.signal)
        const filteredScopes = Object.fromEntries(courts.map(code => [code, { metadata: filteredScope.by_court?.[code] || (courts.length === 1 ? filteredScope.metadata : null) }]))
        const alignmentResult = courts.includes('TJDFT')
          ? await getData('alignment', { ...filters, court: 'TJDFT' }, controller.signal)
          : null
        if (!statistics.metrics || !Array.isArray(instances.series) || !Array.isArray(distribution.series)) throw new Error('A API retornou dados em um formato inesperado.')
        if (!active) return
        if (!applied) setDraft((current) => current.start ? current : { start: available.start || '', end: available.end || '', subject: '' })
        setData({ statistics, instances, distribution, courtScopes, filteredScopes })
        setAlignment(alignmentResult)
        setError('')
      } catch (failure) {
        if (active) {
          setData(null); setAlignment(null)
          setError(failure.name === 'AbortError' ? 'A consulta demorou demais. Tente novamente.' : failure instanceof TypeError ? 'Não foi possível conectar ao backend. Verifique a conexão e tente novamente.' : failure.message)
        }
      } finally {
        clearTimeout(timeout)
        if (active) setLoading(false)
      }
    }
    load()
    return () => { active = false; clearTimeout(timeout); controller.abort() }
  }, [applied, retry, court, courts, authorizedCourts])

  function apply(event) {
    event.preventDefault()
    if (!draft.start || !draft.end || draft.start > draft.end) {
      setValidation('Informe um período válido: a data inicial deve ser anterior ou igual à final.')
      return
    }
    setValidation(''); setLoading(true); setError(''); setData(null); setApplied({ ...draft })
  }

  function reset() {
    setDraft({ start: '', end: '', subject: '' })
    setValidation(''); setLoading(true); setError(''); setData(null); setApplied(null); setRetry((value) => value + 1)
  }

  async function exportPdf() {
    if (!data || loading || exporting) return
    const scope = data.statistics.metadata.scope
    setExporting(true); setExportError('')
    try {
      await downloadReport({ court: scope.court, start: scope.start, end: scope.end, ...(scope.subject ? { subject: scope.subject } : {}) })
    } catch (failure) { setExportError(failure.message) }
    finally { setExporting(false) }
  }

  const metrics = data?.statistics.metrics
  const metadata = data?.statistics.metadata
  const empty = data?.statistics.status === 'empty'
  const loadTitle = loading ? 'Carregando dados…' : error ? 'Dados indisponíveis' : 'Nenhum registro no período'
  const unavailableNote = loading ? 'Consultando a base local.' : error ? 'A consulta falhou. Tente novamente.' : 'Sem documentos com resultado binário identificável neste período.'
  const rateNote = metrics?.binary_denominator ? `Base: ${formatNumber(metrics.binary_denominator)} documentos com resultado mais recente identificado. Indicador por documento, não por recurso individual.` : unavailableNote
  const refreshed = metadata?.last_record_refresh
  const subjectOptions = [...Object.values(data?.courtScopes || {}).flatMap((scope) => scope.subjects || []).reduce((subjects, subject) => {
    const current = subjects.get(subject.code)
    subjects.set(subject.code, current
      ? { ...current, record_count: current.record_count + subject.record_count }
      : { ...subject })
    return subjects
  }, new Map()).values()].sort((left, right) => left.name.localeCompare(right.name, 'pt-BR'))
  const selectedSubjectName = subjectOptions.find((subject) => String(subject.code) === String(applied?.subject || draft.subject))?.name

  return <div className="app-shell"><div className="top-rule" />
    <header className="site-header"><a className="brand" href="#main-content" aria-label="DatumLex, ir ao conteúdo"><span className="brand-mark"><img src="/assets/datumlex-logo.jpeg" alt="" /></span><span>DatumLex</span></a><span className="header-context">Análise de Recursos</span></header>
    <main id="main-content" className="dashboard">
      <section className="hero" aria-labelledby="page-title"><span className="eyebrow">Inteligência jurídica · {selectedSubjectName || 'Todos os assuntos'}</span>
        <div className="hero-title-row"><h1 id="page-title">{selectedSubjectName ? `${selectedSubjectName} — ` : ''}{courts.includes('TJDFT') && courts.includes('STJ') ? 'TJDFT × STJ' : court}</h1>
          <div className="methodology-trigger"><button className="info-button" type="button" aria-label="Ver metodologia de cálculo" aria-expanded={isMethodologyOpen} aria-controls="methodology-popover" onClick={() => setIsMethodologyOpen(!isMethodologyOpen)}><Info aria-hidden="true" size={21} /></button>
            {isMethodologyOpen && <aside id="methodology-popover" className="methodology-popover" onKeyDown={(event) => { if (event.key === 'Escape') setIsMethodologyOpen(false) }}><div className="popover-heading"><strong>Como interpretar os dados</strong><button type="button" aria-label="Fechar metodologia" onClick={() => setIsMethodologyOpen(false)}><X aria-hidden="true" size={18} /></button></div>
              <p>Os valores contam documentos do DataJud por data de ajuizamento. Um processo pode aparecer em mais de uma instância. Ter vários assuntos não multiplica a contagem.</p><p>Provimento = providos ÷ (providos + desprovidos). Desprovimento usa a mesma base. No TJDFT, são usados resultados TPU mapeados em G2/TR; no STJ, em SUP, incluindo movimentos específicos de recurso especial com resultado expresso. Resultados parciais, de admissibilidade, não conhecidos e sem evidência datada ficam fora da base binária. Em empate de data e horário, usamos o maior ID do movimento no banco (desempate técnico). Cada documento conta uma vez. Não representa recursos individuais nem a taxa geral do tribunal.</p>
            </aside>}
          </div>
        </div><p>{court === 'TJDFT' ? 'Visão integrada de resultados locais, precedentes e teses do STJ, com evidências, cobertura e limitações da base.' : 'Metadados processuais do STJ em Responsabilidade Civil; a análise de aderência usa teses e precedentes revisados, não apenas processos relacionados.'}</p>
      </section>
      <form className="filter-panel" aria-label="Filtros do dashboard" onSubmit={apply}>
        <div className="filter-grid">
          <div className="filter-field tribunal-filter"><span id="tribunal-label">Tribunais</span><div ref={courtMenuRef} className="tribunal-select" onKeyDown={(event) => { if (event.key === 'Escape') { setCourtMenuOpen(false); courtButtonRef.current?.focus() } }} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setCourtMenuOpen(false) }}><button ref={courtButtonRef} className="tribunal-trigger" type="button" aria-expanded={courtMenuOpen} aria-controls="tribunal-options" aria-labelledby="tribunal-label tribunal-selection" onClick={() => setCourtMenuOpen((open) => !open)}><span id="tribunal-selection">{courts.length === authorizedCourts.length ? 'Todos os tribunais' : courts.join(', ')}</span><ChevronDown size={16} aria-hidden="true" /></button>{courtMenuOpen && <div id="tribunal-options" className="tribunal-options" role="group" aria-label="Selecionar tribunais"><button type="button" className="text-button" title="Selecionar todos os tribunais" onClick={() => selectCourts([...authorizedCourts])}><ListChecks size={19} aria-hidden="true" />Selecionar todos</button>{authorizedCourts.map((option) => <label key={option}><input type="checkbox" checked={courts.includes(option)} aria-disabled={courts.length === 1 && courts.includes(option)} onChange={(event) => selectCourts(event.target.checked ? [...courts, option] : courts.filter((code) => code !== option))} />{option}</label>)}</div>}</div></div>
          <label className="filter-field"><span>Assunto</span><select value={draft.subject} onChange={(event) => setDraft({ ...draft, subject: event.target.value })}><option value="">Todos os assuntos</option>{subjectOptions.map((subject) => <option key={subject.code} value={subject.code}>{subject.name} ({formatNumber(subject.record_count)})</option>)}</select></label>
          <label className="filter-field"><span>Data inicial</span><input type="date" required value={draft.start} min='2016-01-01' max={bounds?.end || undefined} onChange={(event) => setDraft({ ...draft, start: event.target.value })} disabled={!bounds?.start} /></label>
          <label className="filter-field"><span>Data final</span><input type="date" required value={draft.end} min='2016-01-01' max={bounds?.end || undefined} onChange={(event) => setDraft({ ...draft, end: event.target.value })} disabled={!bounds?.end} /></label>
        </div>
        <div className="filter-actions"><button className="apply-button" type="submit" disabled={!bounds?.start}>Aplicar filtros</button><button type="button" className="secondary-button" onClick={reset}>Limpar filtros</button>{activeTab !== 'corpus' && <button type="button" className="secondary-button" disabled={loading || !data || exporting} onClick={exportPdf}>{exporting ? 'Gerando PDF…' : 'Exportar resumo em PDF'}</button>}</div>
        {exportError && <p role="alert">{exportError}</p>}
        <p className="filter-help">Os filtros são compartilhados entre todas as abas; aplique uma vez e navegue mantendo a seleção. Período por data de ajuizamento, não de julgamento. A comparação de precedentes usa decisões locais do TJDFT e referências do STJ no mesmo assunto e período selecionados.</p>
        {validation && <p className="validation-error" role="alert">{validation}</p>}
      </form>
      <nav className="dashboard-tabs" role="tablist" aria-label="Seções do painel">
        <button id="tab-corpus" type="button" role="tab" aria-selected={activeTab === 'corpus'} aria-controls="panel-corpus" className={activeTab === 'corpus' ? 'is-active' : ''} onClick={() => setActiveTab('corpus')}>Acervo por assunto</button>
        <button id="tab-overview" type="button" role="tab" aria-selected={activeTab === 'overview'} aria-controls="panel-overview" className={activeTab === 'overview' ? 'is-active' : ''} onClick={() => setActiveTab('overview')}>Visão geral</button>
        {courts.includes('TJDFT') && <button id="tab-precedents" type="button" role="tab" aria-selected={activeTab === 'precedents'} aria-controls="panel-precedents" className={activeTab === 'precedents' ? 'is-active' : ''} onClick={() => setActiveTab('precedents')}>Precedentes e teses</button>}
        <button id="tab-sources" type="button" role="tab" aria-selected={activeTab === 'sources'} aria-controls="panel-sources" className={activeTab === 'sources' ? 'is-active' : ''} onClick={() => setActiveTab('sources')}>Fontes e cobertura</button>
      </nav>
      <div className="data-status" role={activeTab === 'corpus' ? 'status' : error ? 'alert' : 'status'}>
        {activeTab === 'corpus' ? 'Acervo de fontes jurídicas locais. As contagens abaixo são separadas dos metadados de processos da visão geral.' : loading ? `Consultando os dados do ${court}…` : error ? <>{error} <button className="secondary-button" onClick={() => { setLoading(true); setError(''); setRetry((value) => value + 1) }}>Tentar novamente</button></> : empty ? 'Nenhum registro carregado corresponde ao período selecionado.' : <>Amostra parcial: <strong>{formatNumber(metrics?.process_records)} registros</strong> no período de {formatDate(metadata?.scope.start)} a {formatDate(metadata?.scope.end)}. Não representa todos os processos do tribunal.</>}
      </div>
      {activeTab === 'overview' && <div id="panel-overview" role="tabpanel" aria-labelledby="tab-overview">
      <section className="indicator-grid" aria-label="Indicadores do recorte selecionado" aria-busy={loading}>
        <IndicatorCard label="Registros de processos no recorte" value={formatNumber(metrics?.process_records)} accent="navy" note={metrics ? `${formatNumber(metrics.distinct_process_numbers)} números de processo distintos; não é uma contagem de recursos julgados.` : unavailableNote} />
        <IndicatorCard label="Taxa de provimento" value={formatRate(metrics?.grant_rate)} accent="green" note={rateNote} />
        <IndicatorCard label="Taxa de desprovimento" value={formatRate(metrics?.denial_rate)} accent="gold" note={rateNote} />
      </section>
      <section className="chart-grid" aria-label="Gráficos do recorte selecionado" aria-busy={loading}>
        <ChartCard title="Registros por trimestre" description={`Volume por instância e data de ajuizamento — ${court}`}>{data?.instances.series.length ? <InstanceChart series={data.instances.series} /> : <ChartState title={loadTitle}>{loading ? 'Buscando a distribuição por instância.' : error ? 'A distribuição será exibida quando a conexão for restabelecida.' : 'Experimente outro período ou limpe os filtros.'}</ChartState>}</ChartCard>
        <ChartCard title={court === 'STJ' ? 'Resultado de mérito' : 'Proporção geral'} description="Providos × Desprovidos no recorte selecionado">
          {data?.distribution.series.some((row) => row.count > 0) ? <>
            <OutcomeChart series={data.distribution.series} />
            <p className="chart-note">{rateNote}</p>
          </> : <ChartState title={loading || error ? loadTitle : 'Sem base para calcular as taxas'}>{unavailableNote}</ChartState>}
          {metrics?.excluded && <details className="chart-table"><summary>Consultar exclusões da base</summary><p className="chart-note">Fora da base: {formatNumber(metrics.excluded.partial)} parciais; {formatNumber(metrics.excluded.ambiguous)} ambíguos; {formatNumber(metrics.excluded.not_admitted + metrics.excluded.partial_knowledge)} não conhecidos, conhecidos em parte ou sem julgamento de mérito; {formatNumber(metrics.excluded.unknown)} sem resultado mapeado; {formatNumber(metrics.excluded.outside_appellate_degree)} de outras instâncias.</p></details>}
        </ChartCard>
      </section>
      </div>}
      {activeTab === 'corpus' && <div id="panel-corpus" role="tabpanel" aria-labelledby="tab-corpus"><CorpusPanel key={`${court}:${applied?.start || bounds.start}:${applied?.end || bounds.end}`} court={court} start={applied?.start || bounds.start} end={applied?.end || bounds.end} /></div>}
      {activeTab === 'precedents' && courts.includes('TJDFT') && <section id="panel-precedents" className="tab-content" role="tabpanel" aria-labelledby="tab-precedents" aria-busy={loading}>
        <div className="precedent-heading-row"><div className="alignment-heading"><span className="eyebrow">NLP explicável</span><h2 id="alignment-title">Precedentes e teses</h2><p>Teses identificadas em decisões com seus trechos e fontes de apoio.</p></div><details className="precedent-limits"><summary>ⓘ Limites da classificação</summary><p>Classificação assistida. As avaliações mostradas foram revisadas; sugestões por identificador ainda precisam de revisão e não comprovam aderência jurídica. A frequência conta referências STJ com tese agrupada.</p></details></div>
        {!alignment ? <ChartState title={loading ? 'Carregando avaliações…' : 'Avaliações indisponíveis'}>A consulta ao corpus revisado não foi concluída.</ChartState> : <>
          {(() => {
            const groups = alignment.thesis_groups || []
            const selectedGroup = groups.find((group) => group.id === selectedThesisId)
            const normalizeText = (value) => (value || '').trim().toLocaleLowerCase().replace(/\s+/g, ' ')
            const selectedKey = selectedGroup ? normalizeText(selectedGroup.title) : null
            const selectedReferenceIds = selectedGroup ? new Set([
              ...(alignment.source_theses || [])
                .filter((reference) => normalizeText(reference.thesis || reference.title) === selectedKey)
                .map((reference) => reference.identifier),
              ...(selectedGroup.source_references || []).map((reference) => reference.identifier),
            ]) : null
            const belongsToSelectedGroup = (identifier) => !selectedReferenceIds || selectedReferenceIds.has(identifier)
            const visibleAssessments = (alignment.assessments || []).filter((item) => belongsToSelectedGroup(item.reference?.identifier))
            const candidateLinks = (alignment.candidate_links || []).map((item) => ({ ...item, kind: 'candidate' }))
            const unresolvedCandidates = (alignment.unresolved_candidates || []).map((item) => ({ ...item, kind: 'candidate', candidate_type: 'unresolved' }))
            const visibleCandidates = [...candidateLinks, ...unresolvedCandidates].filter((item) => belongsToSelectedGroup(item.reference_identifier))
            const maxCount = Math.max(1, ...groups.map((group) => group.case_count || 0))
            const pendingReviews = alignment.metadata?.review_queue?.pending_or_unreviewed ?? 0
            const candidateLimit = alignment.metadata?.candidate_link_coverage?.display_limit
            const candidateTotals = alignment.metadata?.candidate_link_coverage
            const candidateTotal = selectedGroup ? visibleCandidates.length : (candidateTotals?.matched || 0) + (candidateTotals?.unresolved || 0)
            const selectedCourts = ['TJDFT', 'STJ'].filter((courtCode) => courts.includes(courtCode))
            const evidenceBadge = selectedCourts.length > 1 ? selectedCourts.join(' + ') : `Somente ${selectedCourts[0]}`

            return <>
          <div className="precedent-grid">
            <article className="thesis-card"><header className="precedent-card-heading"><div><span className="section-kicker">FREQUÊNCIA</span><h3>Principais teses no recorte</h3><p>Exemplo de agrupamento por tese identificada.</p></div><span className="design-badge">NLP + revisão</span></header>
              {groups.length ? <ol className="thesis-list">{groups.map((group) => {
                const fullTitle = group.title || group.label || group.titulo || 'Tese sem título'
                const sourceReferences = group.source_references || []
                const selected = selectedThesisId === group.id
                return <li key={group.id} className={`thesis-row${selected ? ' is-selected' : ''}`}>
                  <button type="button" className="thesis-row-main" aria-pressed={selected} title={fullTitle} onClick={() => setSelectedThesisId((current) => current === group.id ? null : group.id)}>
                    <strong>{shortThesisLabel(group)}</strong>
                  </button>
                  <div className="thesis-distribution"><div className="thesis-track" role="progressbar" aria-label={`Quantidade de referências: ${formatNumber(group.case_count)}`} aria-valuemin="0" aria-valuemax={maxCount} aria-valuenow={group.case_count || 0}><div className="thesis-track-fill" style={{ width: `${Math.max(0, ((group.case_count || 0) / maxCount) * 100)}%` }} /></div><span className="thesis-count">{formatNumber(group.case_count)} {group.case_count === 1 ? 'referência' : 'referências'}</span></div>
                  <div className="thesis-row-meta"><small>Fontes: {sourceReferences.map((reference) => <a key={reference.identifier} href={reference.source_url} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>{reference.identifier}</a>).reduce((previous, current) => previous ? <>{previous} · {current}</> : current, null)}</small>{!group.approved && <span className="review-pending-badge">Revisão pendente</span>}</div>
                  <details className="thesis-full-text"><summary>Ver enunciado completo</summary><p className="thesis-statement">{fullTitle}</p></details>
                </li>
              })}</ol> : <ChartState title="Nenhuma tese disponível">As teses aparecem após a importação das fontes do STJ.</ChartState>}
            </article>
            <article className="related-card"><header className="precedent-card-heading"><div><span className="section-kicker">EVIDÊNCIAS</span><h3>Decisões relacionadas</h3><p>Processos citados pelas fontes e avaliações locais, apresentados separadamente.</p></div><span className="design-badge">{evidenceBadge}</span></header>
              {visibleAssessments.length ? <div className="related-list">{visibleAssessments.slice(0, 5).map((item) => <article className="related-item evidence-item" key={`${item.local_source_id}-${item.reference.identifier}`}>
                <span className={`evidence-status-icon evidence-status-icon--${item.relation}`} aria-hidden="true">{item.relation === 'aligned' ? '✓' : item.relation === 'divergent' ? '!' : 'i'}</span>
                <div className="evidence-item-content"><h4>{relationLabels[item.relation]} · {item.local_process_number}</h4><p>{item.reference.title}</p><small>{item.reference.identifier}</small></div>
                <button type="button" className="source-drawer-button" onClick={() => setEvidenceDrawerItem({ ...item, kind: 'assessment' })}>Ver fontes →</button>
              </article>)}</div> : <details className="candidate-empty-state local-review-details"><summary>Avaliações locais TJDFT × STJ{pendingReviews ? ` · ${formatNumber(pendingReviews)} pendentes` : ' · ainda não cadastradas'}</summary>
                <div className="pending-summary"><strong>{pendingReviews ? `${formatNumber(pendingReviews)} avaliações aguardando revisão` : 'Nenhuma avaliação jurídica cadastrada'}</strong><p>As avaliações jurídicas dependem de revisão. As citações disponíveis na fonte aparecem abaixo, mesmo sem vínculo com um processo local.</p><p>{formatNumber(candidateTotal)} relações candidatas{selectedGroup ? ` retornadas para “${shortThesisLabel(selectedGroup)}”` : ' no recorte'}{candidateLimit ? ` · a lista exibe até ${formatNumber(candidateLimit)}` : ''}.</p></div>
                {visibleCandidates.length ? <div className="related-list">{visibleCandidates.slice(0, 8).map((item) => <article className="related-item evidence-item" key={`${item.local_source_id}-${item.reference_identifier}-${item.cited_identifier}`}>
                  <span className="evidence-status-icon evidence-status-icon--pending" aria-hidden="true">!</span>
                  <div className="evidence-item-content"><span className="review-pending-badge">Pendente de revisão</span><h4>{item.local_process_number || item.cited_identifier}</h4><p>{item.reference_title}</p><small>{item.reference_identifier}{item.candidate_type === 'unresolved' ? ' · citação sem correspondência local' : item.review_status === 'confirmed' ? ' · identificador confirmado; pertinência ainda não revisada' : ' · sugestão de correspondência'}</small></div>
                  <button type="button" className="source-drawer-button" onClick={() => setEvidenceDrawerItem({ ...item, kind: 'candidate' })}>Ver fontes →</button>
                </article>)}</div> : <p className="candidate-no-links">{selectedGroup ? 'Nenhuma relação candidata retornada para esta tese. Limpe a seleção para ver o recorte completo.' : 'Nenhuma relação candidata retornada pela API neste recorte.'}</p>}
              </details>}
              <SourceDecisions references={alignment.source_theses || []} selectedIdentifiers={selectedReferenceIds} />
            </article>
          </div>
          {selectedGroup && <p className="thesis-selection-note">Filtrando evidências por: <strong>{shortThesisLabel(selectedGroup)}</strong> <button type="button" className="text-button" onClick={() => setSelectedThesisId(null)}>Limpar seleção</button></p>}
          <EvidenceDrawer item={evidenceDrawerItem} onClose={() => setEvidenceDrawerItem(null)} />
            </>
          })()}
        </>}
      </section>}
      {activeTab === 'sources' && <section id="panel-sources" className="tab-content" role="tabpanel" aria-labelledby="tab-sources">
        <div className="alignment-heading"><span className="eyebrow">Rastreabilidade</span><h2>Fontes, cobertura e limitações</h2><p>Consulte origem, período disponível e situação de cada extração. As contagens abaixo refletem os dados carregados localmente, não a cobertura total dos tribunais.</p></div>
        <div className="source-cards">{courts.map((courtCode) => {
          const sourceData = data?.filteredScopes?.[courtCode]?.metadata
          const latest = sourceData?.latest_run
          const available = sourceData?.available_period
          return <article className="source-card" key={courtCode}><span className="section-kicker">DataJud · CNJ</span><h3>{courtCode}</h3>
            <dl><div><dt>Registros carregados no recorte</dt><dd>{formatNumber(sourceData?.loaded_records)}</dd></div>
              <div><dt>Período carregado</dt><dd>{available?.start ? `${formatDate(available.start)} a ${formatDate(available.end)}` : 'Sem registros no período'}</dd></div>
              <div><dt>Última execução</dt><dd>{latest ? `#${latest.id} · ${latest.status} · ${formatNumber(latest.fetched)} lidos, ${formatNumber(latest.rejected)} rejeitados` : 'Sem execução registrada'}</dd></div>
              <div><dt>Data da análise</dt><dd>Ajuizamento; a data do processo não equivale à data de julgamento.</dd></div></dl>
            <p>{sourceData?.coverage || 'Aguardando carregamento dos metadados.'}</p>
          </article>
        })}</div>
        {alignment && <div className="source-card corpus-card"><span className="section-kicker">Corpus jurídico</span><h3>Precedentes STJ e doutrina BDJur</h3><div className="alignment-metrics">
          <IndicatorCard label="Precedentes aprovados" value={formatNumber(alignment.metadata.approved_references.precedents)} accent="navy" note="Referências rastreáveis cadastradas no corpus" />
          <IndicatorCard label="Doutrinas BDJur aprovadas" value={formatNumber(alignment.metadata.approved_references.doctrine)} accent="green" note="Fontes de apoio; não integram a taxa de aderência" />
          <IndicatorCard label="Avaliações pendentes" value={formatNumber(alignment.metadata.review_queue.pending_or_unreviewed)} accent="gold" note="Não entram nos indicadores até validação" />
          <IndicatorCard label="Vínculos validados" value={formatNumber(alignment.metrics.validated_links)} accent="slate" note="Decisão TJDFT relacionada a precedente STJ aprovado" />
        </div>
          <p>Última importação de referência aprovada: {alignment.metadata.last_corpus_import ? new Date(alignment.metadata.last_corpus_import).toLocaleString('pt-BR') : 'nenhuma'}.</p>
          <p>{alignment.metadata.coverage}</p><ul className="limitations-list">{alignment.metadata.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
          {alignment.metadata.pangea_imports?.length > 0 && <details className="chart-table"><summary>Histórico de importação Pangea (últimas 5 execuções)</summary><table><caption>Consulta pública de precedentes dos tribunais selecionados; totais informados pela fonte</caption><thead><tr><th scope="col">Execução</th><th scope="col">Consulta</th><th scope="col">Estado</th><th scope="col">Cobertura</th><th scope="col">Registros</th><th scope="col">Catálogo</th><th scope="col">Erro</th></tr></thead><tbody>{alignment.metadata.pangea_imports.map((run) => <tr key={run.id}><td>#{run.id}<br />{run.started_at ? new Date(run.started_at).toLocaleString('pt-BR') : '—'}</td><td>{run.scope?.query || '—'} · {run.scope?.organs?.join(', ') || '—'}</td><td>{run.status}</td><td>{formatNumber(run.pages)} páginas · {formatNumber(run.fetched)} de {run.source_total == null ? '—' : formatNumber(run.source_total)}</td><td>{formatNumber(run.created)} novos · {formatNumber(run.updated)} atualizados · {formatNumber(run.rejected)} rejeitados</td><td>{run.catalog_version || '—'}</td><td>{run.error || '—'}</td></tr>)}</tbody></table></details>}
          <p>As teses e decisões relacionadas exibem até 300 referências para inspeção. Fontes importadas do Pangea permanecem não aprovadas até revisão humana.</p>
          {alignment.metadata.sources.length > 0 ? <ul className="source-links">{alignment.metadata.sources.map((source) => <li key={`${source.source_institution}-${source.source_name}-${source.identifier}`}><a href={source.source_url} target="_blank" rel="noreferrer">{source.source_institution} · {source.source_name}: {source.identifier} · {source.title}</a>{source.source_locator && ` — ${source.source_locator}`}{source.approval_reference && ` · aprovação ${source.approval_reference}`}</li>)}</ul> : <ChartState title="Corpus aprovado ainda não importado">Precedentes, teses e doutrina só aparecerão após a importação das fontes aprovadas pelo fluxo BDJur.</ChartState>}
        </div>}
      </section>}
      <footer className="dashboard-footer"><p>Fonte: <a href={metadata?.source_url || 'https://api-publica.datajud.cnj.jus.br/'} target="_blank" rel="noreferrer">{metadata?.source || 'DataJud · Conselho Nacional de Justiça'}</a>. {metadata?.coverage || 'Cobertura parcial dos registros locais.'}</p><p>Última atualização dos registros: {refreshed ? new Date(refreshed).toLocaleString('pt-BR') : '—'} · Painel atualizado a cada 5 minutos enquanto aberto.</p></footer>
      {!loading && data ? <NlpPanel contextKey={JSON.stringify({ courts, ...(metadata?.scope?.start ? { start: metadata.scope.start, end: metadata.scope.end } : {}), ...(applied?.subject ? { subject_codes: [Number(applied.subject)] } : {}) })} /> : <section className="nlp-panel"><h2>Teses e fundamentos com evidências</h2><p role="status">{loading ? 'Aguardando o recorte aplicado do dashboard…' : 'Recorte indisponível. Atualize a consulta para carregar as evidências.'}</p></section>}
    </main>
  </div>
}
