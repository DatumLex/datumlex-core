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
      { code: 301, name: 'Acidente de Trânsito', record_count: 4 },
      { code: 302, name: 'Acidente de Trânsito', record_count: 3 },
    ], subject_groups: [
      { code: 101, name: '', record_count: 4 }, { code: 102, name: '  ', record_count: 10 },
      { code: 301, codes: [301, 302], name: 'Acidente de Trânsito', record_count: 6 },
    ],
  } : resource === 'filter-options' ? {
    default_context: { courts, sources: ['stj_jurisprudence'], outcomes: ['unknown'], subject_codes: [10433] },
    sources: [{ id: 'stj_jurisprudence' }], outcomes: ['unknown'],
  } : resource === 'analysis-snapshots' ? {
    snapshot_id: 'app-chat-snapshot', context: route.request().postDataJSON().context,
    populations: {}, exclusions: {}, data_mode: 'fixture',
  } : resource === 'alignment' ? {
    metadata: { ...metadata, approved_references: { precedents: 7, doctrine: 2 },
      review_queue: { pending_or_unreviewed: 3 }, sources: [], limitations: [], coverage: 'Cobertura de teste' },
    metrics: { validated_links: 4 },
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
  await Promise.all([
    page.waitForResponse(response => response.url().includes('/corpus/') && !new URL(response.url()).searchParams.get('topic')),
    page.getByRole('button', { name: 'Limpar seleção de assunto', exact: true }).click(),
  ])
  assert.equal(await select.inputValue(), '')
  assert.ok(requests.filter(url => url.pathname.endsWith('/statistics/')).every(url => url.searchParams.get('include_precedent_usage') === 'false'))
  assert.equal(requests.filter(url => url.pathname.endsWith('/precedent-usage/')).length, 0)
  await page.getByRole('button', { name: /Todos os tribunais autorizados \(10\)/ }).click()
  assert.equal(await page.locator('#tribunal-options input[type=checkbox]').count(), 10)
  await page.getByRole('button', { name: 'Desmarcar todos', exact: true }).click()
  assert.equal(await page.locator('#tribunal-options input:checked').count(), 0)
  await page.getByText('Selecione pelo menos um tribunal para pesquisar.', { exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: 'Aplicar filtros', exact: true }).isDisabled(), true)
  if (!await page.locator('#tribunal-options').isVisible()) await page.locator('.tribunal-trigger').click()
  await page.locator('#tribunal-options input').first().check()
  await page.locator('#tribunal-options input').first().uncheck()
  assert.equal(await page.locator('#tribunal-options input:checked').count(), 0)
  if (!await page.locator('#tribunal-options').isVisible()) await page.locator('.tribunal-trigger').click()
  await page.getByRole('button', { name: 'Selecionar todos', exact: true }).click()
  await select.waitFor()
  assert.ok(requests.every(url => url.searchParams.get('court')))
  await page.locator('.tribunal-trigger').click()
  assert.match(await page.getByRole('heading', { level: 1 }).innerText(), /10 tribunais selecionados/)
  assert.equal(await page.getByLabel('Assunto CNJ (visão geral)', { exact: true }).count(), 0)
  await page.getByRole('tab', { name: 'Visão geral', exact: true }).click()
  const cnj = page.getByLabel('Assunto CNJ (visão geral)', { exact: true })
  await cnj.waitFor()
  assert.deepEqual(await cnj.locator('option').allTextContents(), [
    'Todos os assuntos', 'Acidente de Trânsito (6)', 'Assunto CNJ 101 (nome não informado) (4)', 'Assunto CNJ 102 (nome não informado) (10)',
  ])
  await cnj.selectOption('101')
  await Promise.all([
    page.waitForResponse(response => response.url().includes('/statistics/') && new URL(response.url()).searchParams.get('subject') === '101'),
    page.getByRole('button', { name: 'Aplicar filtros', exact: true }).click(),
  ])
  await page.getByRole('button', { name: 'Limpar seleção de assunto', exact: true }).click()
  assert.equal(await cnj.inputValue(), '')
  await page.getByRole('tab', { name: 'Acervo por assunto', exact: true }).click()
  await select.waitFor()
  // Clearing global filters must reset local catalog state even at the default period.
  await page.getByLabel('Buscar no título').fill('transporte')
  await page.getByRole('button', { name: 'Buscar', exact: true }).click()
  await page.getByLabel('Somente assuntos com os três tipos').check()
  await page.getByLabel('Incluir referências sem data confirmada').uncheck()
  await page.getByRole('button', { name: 'Doutrina (0)', exact: true }).click()
  await Promise.all([page.waitForResponse(response => {
    const url = new URL(response.url())
    return url.pathname.endsWith('/corpus/') && url.searchParams.get('q') === ''
      && url.searchParams.get('complete_only') === 'false'
      && url.searchParams.get('include_undated') === 'true'
      && url.searchParams.get('category') === 'jurisprudence'
  }), page.getByRole('button', { name: 'Limpar filtros', exact: true }).click()])
  assert.equal(await page.getByLabel('Buscar no título').inputValue(), '')
  assert.equal(await page.getByLabel('Somente assuntos com os três tipos').isChecked(), false)
  assert.equal(await page.getByLabel('Incluir referências sem data confirmada').isChecked(), true)
  // Source coverage must fetch and retain the legal corpus on direct entry and re-entry.
  for (let visit = 0; visit < 2; visit++) {
    await page.getByRole('tab', { name: 'Fontes e cobertura', exact: true }).click()
    await page.getByRole('heading', { name: 'Precedentes STJ e doutrina BDJur', exact: true }).waitFor()
    assert.ok(await page.getByText('Cobertura de teste', { exact: true }).isVisible())
    await page.getByRole('tab', { name: 'Acervo por assunto', exact: true }).click()
    await select.waitFor()
  }
  // The application must mount the chat from the user's active filter context.
  await page.getByRole('tab', { name: 'Chat de análise · IA', exact: true }).click()
  await page.getByRole('heading', { name: 'Chat de análise com fontes · Gemini', exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: 'Enviar pergunta', exact: true }).isDisabled(), true)
  const snapshotRequest = requests.find(url => url.pathname.endsWith('/analysis-snapshots/'))
  assert.ok(snapshotRequest)
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
