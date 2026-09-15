import { useState } from 'react'
import { BarChart3, ChevronDown, Info, X } from 'lucide-react'

const filters = [
  { label: 'Tribunal', value: 'TJDFT', disabled: true },
  { label: 'Assunto', value: 'Responsabilidade Civil', disabled: true },
  { label: 'Período', value: 'Jan/2023 – Set/2026' },
  { label: 'Resultado', value: 'Provido e Desprovido' },
]

const indicators = [
  {
    label: 'Recursos analisados no recorte',
    value: '-',
    accent: 'navy',
    ariaLabel: 'Recursos analisados: dado ainda indisponível',
  },
  {
    label: 'Taxa de provimento',
    value: '-',
    accent: 'green',
    ariaLabel: 'Taxa de provimento: dado ainda indisponível',
  },
  {
    label: 'Desprovidos (decisão original mantida)',
    value: '-',
    accent: 'gold',
    ariaLabel: 'Taxa de recursos desprovidos: dado ainda indisponível',
  },
]

function FilterField({ label, value, disabled }) {
  return (
    <label className="filter-field">
      <span>{label}</span>
      <button type="button" disabled={disabled} aria-label={`${label}: ${value}`}>
        <span>{value}</span>
        <ChevronDown aria-hidden="true" size={18} strokeWidth={1.8} />
      </button>
    </label>
  )
}

function IndicatorCard({ label, value, accent, ariaLabel }) {
  return (
    <article className={`indicator-card indicator-card--${accent}`} aria-label={ariaLabel}>
      <strong>{value}</strong>
      <p>{label}</p>
    </article>
  )
}

function EmptyChartCard({ kicker, title, description, emptyMessage, emptyDescription, legend }) {
  return (
    <section className="chart-card" aria-labelledby={`${title}-chart-title`}>
      <div className="chart-heading">
        <div>
          <span className="section-kicker">{kicker}</span>
          <h2 id={`${title}-chart-title`}>{title}</h2>
          <p>{description}</p>
        </div>
        <BarChart3 aria-hidden="true" size={24} />
      </div>

      <div className="chart-empty" role="status">
        <div className="empty-chart-icon"><BarChart3 aria-hidden="true" size={30} /></div>
        <strong>{emptyMessage}</strong>
        <p>{emptyDescription}</p>
      </div>

      <div className="legend" aria-label={`Legenda: ${title}`}>
        {legend.map((item) => (
          <span key={item.label}><i className={item.color} /> {item.label}</span>
        ))}
      </div>
    </section>
  )
}

function App() {
  const [isMethodologyOpen, setIsMethodologyOpen] = useState(false)

  return (
    <div className="app-shell">
      <div className="top-rule" />

      <header className="site-header">
        <a className="brand" href="#main-content" aria-label="DatumLex, ir ao conteúdo">
          <span className="brand-mark">
            <img src="/assets/datumlex-logo.jpeg" alt="" />
          </span>
          <span>DatumLex</span>
        </a>
        <span className="header-context">Análise de Recursos</span>
      </header>

      <main id="main-content" className="dashboard">
        <section className="hero" aria-labelledby="page-title">
          <span className="eyebrow">Painel de mérito recursal</span>
          <div className="hero-title-row">
            <h1 id="page-title">Taxa de Provimento — TJDFT</h1>
            <div className="methodology-trigger">
              <button
                className="info-button"
                type="button"
                aria-label="Ver metodologia de cálculo"
                aria-expanded={isMethodologyOpen}
                aria-controls="methodology-popover"
                onClick={() => setIsMethodologyOpen((isOpen) => !isOpen)}
              >
                <Info aria-hidden="true" size={21} />
              </button>

              {isMethodologyOpen && (
                <aside id="methodology-popover" className="methodology-popover">
                  <div className="popover-heading">
                    <strong>Como isso é calculado</strong>
                    <button
                      type="button"
                      aria-label="Fechar metodologia"
                      onClick={() => setIsMethodologyOpen(false)}
                    >
                      <X aria-hidden="true" size={18} />
                    </button>
                  </div>
                  <p>
                    Classificação por regras e palavras-chave no texto de{' '}
                    <code>movimentos.nome</code> do DataJud (ex.: “dá-se provimento” → Provido,
                    “nega-se provimento” → Desprovido). Não é NLP/IA — essa é a versão prevista
                    para a Sprint 2/3.
                  </p>
                </aside>
              )}
            </div>
          </div>
          <p>
            Resultado dos recursos julgados: quantos foram providos (favoráveis ao recorrente)
            e quantos foram desprovidos, sobre Responsabilidade Civil.
          </p>
        </section>

        <section className="filter-panel" aria-label="Filtros do dashboard">
          <div className="filter-grid">
            {filters.map((filter) => <FilterField key={filter.label} {...filter} />)}
          </div>
          <button className="apply-button" type="button">Aplicar filtros</button>
        </section>

        <section className="indicator-grid" aria-label="Indicadores do recorte selecionado">
          {indicators.map((indicator) => <IndicatorCard key={indicator.label} {...indicator} />)}
        </section>

        <section className="chart-grid" aria-label="Gráficos do recorte selecionado">
          <EmptyChartCard
            kicker="Distribuição"
            title="Resultado dos recursos"
            description="Provido × Desprovido — Responsabilidade Civil, TJDFT"
            emptyMessage="Dados ainda não disponíveis"
            emptyDescription="O gráfico será preenchido quando a integração com o DataJud estiver ativa."
            legend={[
              { label: 'Provido', color: 'legend-provido' },
              { label: 'Desprovido', color: 'legend-desprovido' },
            ]}
          />

          <EmptyChartCard
            kicker="Instâncias"
            title="G1 vs. G2 por trimestre"
            description="Volume de processos por instância — Responsabilidade Civil, TJDFT"
            emptyMessage="Dados ainda não disponíveis"
            emptyDescription="O histórico por instância será exibido quando a integração com o DataJud estiver ativa."
            legend={[
              { label: 'G1 — 1ª instância', color: 'legend-g1' },
              { label: 'G2 — 2ª instância', color: 'legend-g2' },
            ]}
          />
        </section>

        <footer className="dashboard-footer">
          <p>Fonte: DataJud · Conselho Nacional de Justiça</p>
          <p>Última atualização: —</p>
        </footer>
      </main>
    </div>
  )
}

export default App
