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

function InstanceChart({ series }) {
  const maximum = Math.max(1, ...series.map((row) => row.count))
  return <>
    <p className="chart-note">Contagem por trimestre de ajuizamento. Cada barra parte de zero.</p>
    <div className="instance-bars" aria-label="Registros por trimestre e instância">
      {series.map((row) => <div className="instance-row" key={`${row.time__year}-${row.time__quarter}-${row.degree}`}>
        <span>{row.time__quarter}º tri/{row.time__year} · {row.degree}</span>
        <div className="bar-track" aria-hidden="true"><div className={`bar-fill degree-${row.degree}`} style={{ width: `${100 * row.count / maximum}%` }} /></div><strong>{formatNumber(row.count)}</strong>
      </div>)}
    </div>
    <p className="chart-note">{[...new Set(series.map((row) => row.degree))].map((degree) => `${degree}: ${degrees[degree] || degree}`).join(' · ')}</p>
    <details className="chart-table"><summary>Ver dados em tabela</summary><table>
      <caption>Documentos por trimestre de ajuizamento e instância</caption>
      <thead><tr><th scope="col">Trimestre</th><th scope="col">Instância</th><th scope="col">Registros</th></tr></thead>
      <tbody>{series.map((row) => <tr key={`${row.time__year}-${row.time__quarter}-${row.degree}`}><td>{row.time__quarter}º tri/{row.time__year}</td><td>{row.degree}</td><td>{formatNumber(row.count)}</td></tr>)}</tbody>
    </table></details>
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
        <ChartCard title="Resultados identificados" description="Provido × Desprovido — por documento do DataJud">
          {data?.distribution.series.length ? <>
            <div className="outcome-bars">{data.distribution.series.map((row) => <div key={row.outcome}>
              <p>{row.outcome === 'granted' ? 'Providos' : 'Desprovidos'}: <strong>{formatNumber(row.count)} ({formatRate(row.rate)})</strong></p>
              <div className="bar-track" aria-hidden="true"><div className={`bar-fill degree-${row.outcome === 'granted' ? 'G1' : 'JE'}`} style={{ width: `${row.rate * 100}%` }} /></div>
            </div>)}</div>
            <p className="chart-note">{rateNote}</p>
          </> : <ChartState title={loading || error ? loadTitle : 'Sem base para calcular as taxas'}>{unavailableNote}</ChartState>}
          {metrics?.excluded && <p className="chart-note">Fora da base: {formatNumber(metrics.excluded.partial)} parciais; {formatNumber(metrics.excluded.ambiguous)} ambíguos; {formatNumber(metrics.excluded.not_admitted + metrics.excluded.partial_knowledge)} não conhecidos ou conhecidos em parte; {formatNumber(metrics.excluded.unknown)} sem resultado mapeado em G2/TR; {formatNumber(metrics.excluded.outside_appellate_degree)} de outras instâncias.</p>}
        </ChartCard>
        <ChartCard title="Registros por instância e trimestre" description="Volume por data de ajuizamento — TJDFT">{data?.instances.series.length ? <InstanceChart series={data.instances.series} /> : <ChartState title={loadTitle}>{loading ? 'Buscando a distribuição por instância.' : error ? 'A distribuição será exibida quando a conexão for restabelecida.' : 'Experimente outro período ou limpe os filtros.'}</ChartState>}</ChartCard>
      </section>
      <footer className="dashboard-footer"><p>Fonte: {metadata?.source || 'DataJud · Conselho Nacional de Justiça'}</p><p>Última atualização dos registros: {refreshed ? new Date(refreshed).toLocaleString('pt-BR') : '—'}</p></footer>
    </main>
  </div>
}
