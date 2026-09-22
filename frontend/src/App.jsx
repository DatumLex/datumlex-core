import { useEffect, useState } from 'react'
import { BarChart3, Info, X } from 'lucide-react'
import { getData } from './api'

const number = new Intl.NumberFormat('pt-BR')
const formatNumber = (value) => value == null ? '—' : number.format(value)
const formatRate = (value) => value == null ? '—' : new Intl.NumberFormat('pt-BR', { style: 'percent', maximumFractionDigits: 1 }).format(value)
const formatDate = (value) => value ? new Date(`${value}T12:00:00`).toLocaleDateString('pt-BR') : '—'
const degrees = { G1: '1ª instância', G2: '2ª instância', JE: 'Juizados especiais', TR: 'Turmas recursais', SUP: 'Tribunal superior' }

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

const degreeColors = { G1: '#1f4e5f', G2: '#c9a227', JE: '#3f7452', TR: '#718496', SUP: '#866a96' }

function InstanceChart({ series }) {
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
            return <rect key={degree} x={42 + index * slot + slot * .23} y={272 - accumulated} width={slot * .54} height={height} fill={degreeColors[degree]} tabIndex={count ? 0 : undefined} aria-label={`${period.label}, ${degrees[degree]}: ${formatNumber(count)} documentos`}>
              <title>{period.label} · {degrees[degree]}: {formatNumber(count)} documentos</title>
            </rect>
          })}<text x={42 + (index + .5) * slot} y="294" textAnchor="middle">{period.label}</text></g>
        })}
      </svg>
    </div>
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
  const total = series.reduce((sum, row) => sum + row.count, 0)
  return <>
    <svg className="outcome-donut" viewBox="0 0 360 340" role="img" aria-label={`Proporção de resultados em ${formatNumber(total)} documentos`}>
      {series.map((row, index) => {
        const portion = total ? row.count / total * 100 : 0
        const start = total ? series.slice(0, index).reduce((sum, item) => sum + item.count, 0) / total * 100 : 0
        const label = row.outcome === 'granted' ? 'Providos' : 'Desprovidos'
        return <circle key={row.outcome} cx="180" cy="170" r="124" pathLength="100" fill="none" stroke={row.outcome === 'granted' ? '#1f4e5f' : '#c9a227'} strokeWidth="62" strokeDasharray={`${portion} ${100 - portion}`} strokeDashoffset={-start} transform="rotate(-90 180 170)" tabIndex="0" aria-label={`${label}: ${formatNumber(row.count)} (${formatRate(row.rate)})`}><title>{label}: {formatNumber(row.count)} ({formatRate(row.rate)})</title></circle>
      })}
      <text x="180" y="168" textAnchor="middle" className="donut-total">{formatNumber(total)}</text>
      <text x="180" y="193" textAnchor="middle" className="donut-caption">documentos com resultado</text>
    </svg>
    <div className="chart-legend outcome-legend">{series.map((row) => <span key={row.outcome}><i style={{ background: row.outcome === 'granted' ? '#1f4e5f' : '#c9a227' }} /><span>{row.outcome === 'granted' ? 'Providos' : 'Desprovidos'}<strong>{formatRate(row.rate)} · {formatNumber(row.count)}</strong></span></span>)}</div>
  </>
}

export default function App() {
  const [isMethodologyOpen, setIsMethodologyOpen] = useState(false)
  const [draft, setDraft] = useState({ start: '', end: '' })
  const [applied, setApplied] = useState(null)
  const [bounds, setBounds] = useState(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [validation, setValidation] = useState('')
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    const timeout = setTimeout(() => controller.abort(), 20000)
    async function load() {
      try {
        const scope = await getData('scope', {}, controller.signal)
        const available = scope.metadata.available_period
        const filters = applied || (available.start && available.end ? { start: available.start, end: available.end } : {})
        const [statistics, instances, distribution] = await Promise.all(
          ['statistics', 'instances', 'distribution'].map((resource) => getData(resource, filters, controller.signal)),
        )
        if (!statistics.metrics || !Array.isArray(instances.series) || !Array.isArray(distribution.series)) throw new Error('A API retornou dados em um formato inesperado.')
        if (!active) return
        setBounds(available)
        if (!applied) setDraft({ start: available.start || '', end: available.end || '' })
        setData({ statistics, instances, distribution })
        setError('')
      } catch (failure) {
        if (active) {
          setData(null)
          setError(failure.name === 'AbortError' ? 'A consulta demorou demais. Tente novamente.' : failure instanceof TypeError ? 'Não foi possível conectar ao backend. Verifique a conexão e tente novamente.' : failure.message)
        }
      } finally {
        clearTimeout(timeout)
        if (active) setLoading(false)
      }
    }
    load()
    return () => { active = false; clearTimeout(timeout); controller.abort() }
  }, [applied, retry])

  function apply(event) {
    event.preventDefault()
    if (!draft.start || !draft.end || draft.start > draft.end) {
      setValidation('Informe um período válido: a data inicial deve ser anterior ou igual à final.')
      return
    }
    setValidation(''); setLoading(true); setError(''); setData(null); setApplied({ ...draft })
  }

  function reset() {
    setValidation(''); setLoading(true); setError(''); setData(null); setApplied(null); setRetry((value) => value + 1)
  }

  const metrics = data?.statistics.metrics
  const metadata = data?.statistics.metadata
  const empty = data?.statistics.status === 'empty'
  const loadTitle = loading ? 'Carregando dados…' : error ? 'Dados indisponíveis' : 'Nenhum registro no período'
  const unavailableNote = loading ? 'Consultando a base local.' : error ? 'A consulta falhou. Tente novamente.' : 'Sem documentos com resultado binário identificável neste período.'
  const rateNote = metrics?.binary_denominator ? `Base: ${formatNumber(metrics.binary_denominator)} documentos com resultado mais recente identificado. Indicador por documento, não por recurso individual.` : unavailableNote
  const refreshed = metadata?.last_record_refresh

  return <div className="app-shell"><div className="top-rule" />
    <header className="site-header"><a className="brand" href="#main-content" aria-label="DatumLex, ir ao conteúdo"><span className="brand-mark"><img src="/assets/datumlex-logo.jpeg" alt="" /></span><span>DatumLex</span></a><span className="header-context">Análise de Recursos</span></header>
    <main id="main-content" className="dashboard">
      <section className="hero" aria-labelledby="page-title"><span className="eyebrow">Painel de mérito recursal</span>
        <div className="hero-title-row"><h1 id="page-title">Taxa de Provimento — TJDFT</h1>
          <div className="methodology-trigger"><button className="info-button" type="button" aria-label="Ver metodologia de cálculo" aria-expanded={isMethodologyOpen} aria-controls="methodology-popover" onClick={() => setIsMethodologyOpen(!isMethodologyOpen)}><Info aria-hidden="true" size={21} /></button>
            {isMethodologyOpen && <aside id="methodology-popover" className="methodology-popover" onKeyDown={(event) => { if (event.key === 'Escape') setIsMethodologyOpen(false) }}><div className="popover-heading"><strong>Como interpretar os dados</strong><button type="button" aria-label="Fechar metodologia" onClick={() => setIsMethodologyOpen(false)}><X aria-hidden="true" size={18} /></button></div>
              <p>Os valores contam documentos do DataJud por data de ajuizamento. Um processo pode aparecer em mais de uma instância. Ter vários assuntos não multiplica a contagem.</p><p>Provimento = providos ÷ (providos + desprovidos). Desprovimento usa a mesma base. Último resultado por data do movimento TPU em G2/TR: 237/972 para provimento e 239 para desprovimento. Resultados anteriores não excluem o documento. Em empate de data e horário, usamos o maior ID do movimento no banco (desempate técnico). Resultados mais recentes parciais, não conhecidos e sem evidência datada ficam fora da base binária. Cada documento conta uma vez. Não representa recursos individuais nem a taxa geral do tribunal.</p>
            </aside>}
          </div>
        </div><p>Provimento e desprovimento nos documentos de Responsabilidade Civil carregados do DataJud. Amostra parcial, pelo resultado mais recente de cada documento.</p>
      </section>
      <form className="filter-panel" aria-label="Filtros do dashboard" onSubmit={apply}>
        <div className="filter-grid">
          <label className="filter-field"><span>Tribunal</span><select disabled value="TJDFT"><option>TJDFT</option></select></label>
          <label className="filter-field"><span>Assunto</span><select disabled value="civil"><option value="civil">Responsabilidade Civil</option></select></label>
          <label className="filter-field"><span>Data inicial</span><input type="date" required value={draft.start} min={bounds?.start || '2023-01-01'} max={bounds?.end || undefined} onChange={(event) => setDraft({ ...draft, start: event.target.value })} disabled={!bounds?.start} /></label>
          <label className="filter-field"><span>Data final</span><input type="date" required value={draft.end} min={bounds?.start || '2023-01-01'} max={bounds?.end || undefined} onChange={(event) => setDraft({ ...draft, end: event.target.value })} disabled={!bounds?.end} /></label>
        </div>
        <div className="filter-actions"><button className="apply-button" type="submit" disabled={!bounds?.start}>Aplicar filtros</button><button type="button" className="secondary-button" onClick={reset}>Limpar filtros</button></div>
        <p className="filter-help">Período por data de ajuizamento, não de julgamento. Tribunal e assunto fixos neste recorte.</p>
        {validation && <p className="validation-error" role="alert">{validation}</p>}
      </form>
      <div className="data-status" role={error ? 'alert' : 'status'}>
        {loading ? 'Consultando os dados do TJDFT…' : error ? <>{error} <button className="secondary-button" onClick={() => { setLoading(true); setError(''); setRetry((value) => value + 1) }}>Tentar novamente</button></> : empty ? 'Nenhum registro carregado corresponde ao período selecionado.' : <>Amostra parcial: <strong>{formatNumber(metrics?.process_records)} registros</strong> no período de {formatDate(metadata?.scope.start)} a {formatDate(metadata?.scope.end)}. Não representa todos os processos do tribunal.</>}
      </div>
      <section className="indicator-grid" aria-label="Indicadores do recorte selecionado" aria-busy={loading}>
        <IndicatorCard label="Registros de processos no recorte" value={formatNumber(metrics?.process_records)} accent="navy" note={metrics ? `${formatNumber(metrics.distinct_process_numbers)} números de processo distintos; não é uma contagem de recursos julgados.` : unavailableNote} />
        <IndicatorCard label="Taxa de provimento" value={formatRate(metrics?.grant_rate)} accent="green" note={rateNote} />
        <IndicatorCard label="Taxa de desprovimento" value={formatRate(metrics?.denial_rate)} accent="gold" note={rateNote} />
      </section>
      <section className="chart-grid" aria-label="Gráficos do recorte selecionado" aria-busy={loading}>
        <ChartCard title="Registros por trimestre" description="Volume por instância e data de ajuizamento — TJDFT">{data?.instances.series.length ? <InstanceChart series={data.instances.series} /> : <ChartState title={loadTitle}>{loading ? 'Buscando a distribuição por instância.' : error ? 'A distribuição será exibida quando a conexão for restabelecida.' : 'Experimente outro período ou limpe os filtros.'}</ChartState>}</ChartCard>
        <ChartCard title="Proporção geral" description="Providos × Desprovidos no recorte selecionado">
          {data?.distribution.series.some((row) => row.count > 0) ? <>
            <OutcomeChart series={data.distribution.series} />
            <p className="chart-note">{rateNote}</p>
          </> : <ChartState title={loading || error ? loadTitle : 'Sem base para calcular as taxas'}>{unavailableNote}</ChartState>}
          {metrics?.excluded && <details className="chart-table"><summary>Consultar exclusões da base</summary><p className="chart-note">Fora da base: {formatNumber(metrics.excluded.partial)} parciais; {formatNumber(metrics.excluded.ambiguous)} ambíguos; {formatNumber(metrics.excluded.not_admitted + metrics.excluded.partial_knowledge)} não conhecidos ou conhecidos em parte; {formatNumber(metrics.excluded.unknown)} sem resultado mapeado em G2/TR; {formatNumber(metrics.excluded.outside_appellate_degree)} de outras instâncias.</p></details>}
        </ChartCard>
      </section>
      <footer className="dashboard-footer"><p>Fonte: {metadata?.source || 'DataJud · Conselho Nacional de Justiça'}</p><p>Última atualização dos registros: {refreshed ? new Date(refreshed).toLocaleString('pt-BR') : '—'}</p></footer>
    </main>
  </div>
}
