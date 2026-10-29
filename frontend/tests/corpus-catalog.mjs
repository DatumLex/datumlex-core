// Synthetic legal catalog fixtures. No collectors or production database writes.
import assert from 'node:assert/strict'
import { chromium } from '@playwright/test'
const origin = process.env.FRONTEND_URL || 'http://127.0.0.1:5199'
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } })
const errors = []
const requests = []
page.on('pageerror', (error) => errors.push(error.message))
await page.route('**/api/corpus/**', async (route) => {
  const params = new URL(route.request().url()).searchParams
  requests.push(Object.fromEntries(params))
  const category = params.get('category') || 'jurisprudence'
  const empty = params.get('q') === 'vazio'
  const counts = empty ? { jurisprudence: 0, precedent: 0, doctrine: 0 } : { jurisprudence: 13, precedent: 2, doctrine: 1 }
  const fixture = { counts, topics: [{ id: 'dano-moral', label: 'Dano moral', counts, has_all_three: !empty }],
    items: empty ? [] : [{ id: 1, title: category === 'doctrine' ? 'Artigo de teste sobre dano moral' : 'Documento de teste sobre dano moral',
      category, court: category === 'doctrine' ? '' : params.get('court'), source_name: 'Fonte de teste',
      source_url: category === 'precedent' ? 'javascript:alert(1)' : 'https://www12.senado.leg.br/',
      content_kind: category === 'doctrine' ? 'doctrine_article' : category === 'precedent' ? 'precedent_reference' : 'full_text',
      date: category === 'precedent' ? null : '2024-03-15', period_confirmed: category !== 'precedent',
      authors: category === 'doctrine' ? ['Autoria de teste'] : [], review_status: 'pending', excerpt: '<script>window.injected=true</script>Trecho de teste.' }],
    pagination: { total: counts[category], has_next: category === 'jurisprudence' && params.get('page') === '1' }, coverage: { undated: empty ? 0 : 2 } }
  await route.fulfill({ contentType: 'application/json', body: JSON.stringify(fixture) })
})
await page.route('**/__corpus_test__', (route) => route.fulfill({ contentType: 'text/html', body: `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"></head><body><main class="dashboard"><div id="root"></div></main><script type="module">
import React from '/node_modules/.vite/deps/react.js';
import ReactDOM from '/node_modules/.vite/deps/react-dom_client.js';
import RefreshRuntime from '/@react-refresh';
RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;
const { default: CorpusPanel } = await import('/src/CorpusPanel.jsx');
import '/src/index.css';
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(CorpusPanel,{court:'TJSP',start:'2016-01-01',end:'2026-10-29'}));
</script></body></html>` }))
try {
  await page.goto(`${origin}/__corpus_test__`)
  await page.getByRole('heading', { name: 'Acervo por assunto' }).waitFor()
  await page.locator('.corpus-result').waitFor()
  assert.equal(requests.at(-1).court, 'TJSP')
  assert.equal(await page.locator('.corpus-count').count(), 3)
  await Promise.all([page.waitForResponse((response) => response.url().includes('topic=dano-moral')), page.locator('.corpus-topics button').filter({ hasText: 'Dano moral' }).click()])
  await Promise.all([page.waitForResponse((response) => response.url().includes('page=2')), page.getByRole('button', { name: 'Próxima', exact: true }).click()])
  await page.getByRole('button', { name: 'Doutrina (1)', exact: true }).click()
  await page.getByRole('heading', { name: 'Artigo de teste sobre dano moral', exact: true }).waitFor()
  assert.equal(requests.at(-1).page, '1')
  assert.ok(await page.getByText('Autoria de teste', { exact: true }).isVisible())
  await page.getByText('Consultar trecho inicial', { exact: true }).click()
  assert.equal(await page.evaluate(() => window.injected), undefined)
  assert.ok(await page.getByText(/<script>window.injected/).isVisible())
  await Promise.all([page.waitForResponse((response) => response.url().includes('complete_only=true')), page.getByLabel('Somente assuntos com os três tipos').check()])
  await Promise.all([page.waitForResponse((response) => response.url().includes('include_undated=false')), page.getByLabel('Incluir referências sem data confirmada').uncheck()])
  for (const width of [320, 760, 1280]) {
    await page.setViewportSize({ width, height: 1000 })
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `Horizontal overflow at ${width}px`)
    if (width === 320 || width === 1280) await page.screenshot({ path: `tests/corpus-${width}.png`, fullPage: true })
  }
  await page.getByRole('button', { name: 'Precedentes (2)', exact: true }).click()
  await page.getByText('Link público não informado.', { exact: true }).waitFor()
  assert.equal(await page.locator('a[href^="javascript:"]').count(), 0)
  await page.getByLabel('Buscar no título').fill('vazio')
  await page.getByRole('button', { name: 'Buscar', exact: true }).click()
  await page.getByText(/Nenhum documento deste tipo corresponde/).waitFor()
  // The full App must expose this catalog without requiring TJDFT or DataJud availability.
  await page.route('**/api/**', (route) => route.request().url().includes('/api/corpus/')
    ? route.fallback() : route.fulfill({ status: 503, contentType: 'application/json', body: '{}' }))
  await page.route('**/__corpus_app__', (route) => route.fulfill({ contentType: 'text/html', body: `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"></head><body><div id="root"></div><script type="module">
import React from '/node_modules/.vite/deps/react.js';
import ReactDOM from '/node_modules/.vite/deps/react-dom_client.js';
import RefreshRuntime from '/@react-refresh';
RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;
const { default: App } = await import('/src/App.jsx');
import '/src/index.css';
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App,{court:'TJSP',courts:['TJSP','STJ']}));
</script></body></html>` }))
  await page.goto(`${origin}/__corpus_app__`)
  await page.getByRole('tab', { name: 'Acervo por assunto', exact: true }).waitFor()
  await page.locator('.corpus-result').waitFor()
  assert.equal(requests.at(-1).court, 'TJSP,STJ')
  assert.equal(await page.getByRole('tab', { name: 'Acervo por assunto', exact: true }).getAttribute('aria-selected'), 'true')
  assert.match(await page.locator('.data-status').innerText(), /Acervo de fontes jurídicas locais/)
  assert.deepEqual(errors, [])
  console.log('Corpus UI passed: three types, topic, pagination, dates, safe text/links, empty state and 320/760/1280px layouts.')
} finally { await browser.close() }
