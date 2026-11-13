// Synthetic API responses: no live accounts or database access.
import assert from 'node:assert/strict'
import { chromium } from '@playwright/test'

const origin = process.env.FRONTEND_URL || 'http://127.0.0.1:5199'
const courts = ['STJ', 'TJDFT', 'TJSP', 'TJMG', 'TJRJ', 'TJRS', 'TJPR', 'TRF1', 'TRF3', 'TST']
const themes = [
  ['dano-moral', 'Dano moral'], ['dano-material', 'Dano material e reparação integral'],
  ['saude', 'Responsabilidade em serviços de saúde'], ['transito', 'Acidentes de trânsito'],
  ['negativacao', 'Negativação indevida'], ['transporte-aereo', 'Transporte aéreo'],
  ['imovel', 'Atraso na entrega de imóvel'], ['imagem', 'Imagem, honra e privacidade'],
  ['perda-chance', 'Perda de uma chance'], ['internet', 'Responsabilidade na internet'],
]
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } })
const errors = []
const requests = []
page.on('pageerror', error => errors.push(error.message))
await page.route('**/api/**', route => {
  const url = new URL(route.request().url())
  requests.push(url)
  const scope = { court: url.searchParams.get('court'), start: '2016-01-01', end: '2026-11-13' }
  const metadata = { scope, available_period: { start: '2016-01-01', end: '2026-11-13' } }
  const counts = { jurisprudence: 0, precedent: 0, doctrine: 0 }
  const resource = url.pathname.split('/').filter(Boolean).at(-1)
  const body = resource === 'corpus' ? {
    scope, counts, topics: themes.map(([id, label]) => ({ id, label, counts, has_all_three: false })),
    items: [], pagination: { total: 0, has_next: false }, coverage: { undated: 0 },
  } : resource === 'scope' ? {
    metadata, by_court: {}, subjects: [
      { code: 101, name: '', record_count: 4 }, { code: 102, name: '  ', record_count: 10 },
    ],
  } : resource === 'statistics' ? {
    status: 'empty', metadata, metrics: { process_records: 0, binary_denominator: 0 },
  } : { metadata, series: [] }
  return route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
})
await page.route('**/__dashboard_filters__', route => route.fulfill({
  contentType: 'text/html', body: `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head><body><div id="root"></div><script type="module">
import React from '/node_modules/.vite/deps/react.js';
import ReactDOM from '/node_modules/.vite/deps/react-dom_client.js';
import RefreshRuntime from '/@react-refresh';
RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;
const { default: App } = await import('/src/App.jsx');
import '/src/index.css';
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App,{court:'STJ',courts:${JSON.stringify(courts)}}));
</script></body></html>`,
}))
try {
  await page.goto(`${origin}/__dashboard_filters__`)
  const select = page.getByLabel('Assunto de Responsabilidade Civil (10 temas)', { exact: true })
  await select.waitFor()
  assert.equal(await select.locator('option').count(), 11)
  const labels = await select.locator('option').allTextContents()
  assert.ok(labels.every(label => label.trim()))
  await Promise.all([
    page.waitForResponse(response => response.url().includes('topic=perda-chance')),
    select.selectOption('perda-chance'),
  ])
  assert.ok(requests.some(url => url.searchParams.get('start') === '2016-01-01'))
  await page.getByRole('button', { name: /Todos os tribunais autorizados \(10\)/ }).click()
  assert.equal(await page.locator('#tribunal-options input[type=checkbox]').count(), 10)
  await page.locator('.tribunal-trigger').click()
  assert.match(await page.getByRole('heading', { level: 1 }).innerText(), /10 tribunais selecionados/)
  assert.equal(await page.getByLabel('Assunto CNJ (visão geral)', { exact: true }).count(), 0)
  await page.getByRole('tab', { name: 'Visão geral', exact: true }).click()
  const cnj = page.getByLabel('Assunto CNJ (visão geral)', { exact: true })
  await cnj.waitFor()
  assert.deepEqual(await cnj.locator('option').allTextContents(), [
    'Todos os assuntos', 'Assunto CNJ 101 (nome não informado) (4)', 'Assunto CNJ 102 (nome não informado) (10)',
  ])
  await page.getByRole('tab', { name: 'Acervo por assunto', exact: true }).click()
  await select.waitFor()
  await page.setViewportSize({ width: 320, height: 900 })
  const selectBounds = await select.boundingBox()
  assert.ok(selectBounds.width > 0 && selectBounds.x + selectBounds.width <= 320, 'Topic selector exceeds mobile width')
  assert.deepEqual(errors, [])
  console.log('Passed: 10 court permissions, 10 named topics, pre-2023 dates, CNJ fallback labels, and mobile layout.')
} catch (error) {
  console.error('Browser errors:', errors)
  console.error(await page.evaluate(() => [...document.querySelectorAll('*')].filter(el => el.getBoundingClientRect().right > innerWidth + 1).slice(0,15).map(el => ({tag:el.tagName,cls:el.className,right:el.getBoundingClientRect().right}))))
  console.error((await page.locator('body').innerText()).slice(0, 5000))
  throw error
} finally {
  await browser.close()
}
