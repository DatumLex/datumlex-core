// FX115-BROWSER-01: synthetic API fixtures. No live database or legal approval.
import assert from 'node:assert/strict'
import { chromium } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'

const origin = process.env.FRONTEND_URL || 'http://127.0.0.1:5179'
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
page.on('console', message => { if (message.type() === 'error') console.error('PAGE CONSOLE', message.text()) })
page.on('requestfailed', request => console.error('REQUEST FAILED', request.url(), request.failure()))
const defaults = { contract_version: 'analytical-context-v1', courts: ['STJ'], outcomes: ['granted', 'denied'], sources: ['stj_jurisprudence'], subject_codes: [10433], start: '2024-01-01', end: '2024-12-31' }
let mode = 'ready'
let generation = 0
const snapshots = new Map()
const quote = 'Não houve nexo causal. 😀'
const item = { id: 'FX115-E1', document_id: 'STJ:FX115-D1', court: 'STJ', population: 'decision_text',
  document_metadata: { title: 'Documento sintético FX115-BROWSER-01' }, official_url: 'https://www.stj.jus.br/fixture',
  effective: { segments: [{ start: 0, end: 24, text: quote, locator: { page: null } }], context: {}, confidence: { score: null }, warnings: ['low_confidence'] },
  revision: 1, revision_id: 'FX115-R1', text_version_id: 'FX115-T1', text_sha256: 'fixture-text-hash', extraction_id: 'FX115-X1',
  pipeline: { rules_version: 'fixture-v1' }, source_state: 'changed', source_observation_id: 'FX115-O1', source_checked_at: '2026-10-23T12:00:00Z' }
const group = { id: 'FX115-G1', label: 'Ausência de nexo causal — fixture', document_count: 1, evidence_count: 1 }
const unavailable = { documents_in_scope: 0, documents_quality_released: 0, denominator: 0, period_field: 'publication_date', status: 'unavailable' }
const requests = []

await page.route('**/__nlp_test__', route => route.fulfill({ contentType: 'text/html', body: `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="root"></div><script type="module">
import React from '/node_modules/.vite/deps/react.js';
import ReactDOM from '/node_modules/.vite/deps/react-dom_client.js';
import RefreshRuntime from '/@react-refresh';
RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;
const { default: NlpPanel } = await import('/src/NlpPanel.jsx');
import '/src/index.css';
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(NlpPanel,{contextKey:JSON.stringify(${JSON.stringify(defaults)})}));
</script></body></html>` }))

await page.route('**/api/**', async route => {
  const request = route.request()
  const url = new URL(request.url())
  const json = async data => route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) })
  if (url.pathname.endsWith('/auth/csrf/')) return json({ csrfToken: 'FX115-CSRF' })
  if (url.pathname.endsWith('/filter-options/')) return json({ default_context: defaults, sources: [{ id: 'stj_jurisprudence' }, { id: 'bdjur_doctrine' }], outcomes: ['granted', 'denied'] })
  if (request.method() === 'POST') {
    assert.equal(request.headers()['x-csrftoken'], 'FX115-CSRF')
    const context = request.postDataJSON().context
    requests.push(context)
    if (mode === 'error') return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { message: 'Falha simulada FX115.' } }) })
    const id = `FX115-S${++generation}`
    const snapshot = { snapshot_id: id, query_id: `FX115-Q${generation}`, sha256: 'fixture-snapshot-hash', context,
      data_mode: 'fixture', disclaimer: 'Frequência documental não representa probabilidade de vitória nem autoridade jurídica.',
      exclusions: { unmapped_documents: 1, quality_blocked: 0, missing_text: 1 },
      populations: { decision_text: { ...unavailable, documents_in_scope: 3, documents_quality_released: 1, denominator: 1, period_field: 'decision_date', status: mode === 'unavailable' ? 'unavailable' : !context.sources.length ? 'empty' : 'ready' }, precedent: unavailable, doctrine: unavailable } }
    snapshots.set(id, snapshot)
    if (mode === 'race' && !context.sources.length) await new Promise(resolve => setTimeout(resolve, 250))
    return json(snapshot)
  }
  const id = url.pathname.split('/')[4]
  if (url.pathname.endsWith('/sources/')) return json({ snapshot_id: id, items: [{ ...item, id: url.searchParams.has('cursor') ? 'FX115-E2' : item.id }], total_items: 2, next_cursor: url.searchParams.has('cursor') ? null : 'FX115-CURSOR' })
  if (url.pathname.endsWith('/export/')) return json({ ...snapshots.get(id), items: [item] })
  return json({ snapshot_id: id, items: [group], total_items: 1, next_cursor: null })
})

try {
  await page.goto(`${origin}/__nlp_test__`)
  await page.getByRole('heading', { name: group.label }).waitFor()
  assert.deepEqual(requests.at(-1), defaults)
  await page.getByRole('button', { name: /^Ver fontes/ }).focus()
  await page.keyboard.press('Enter')
  assert.equal(await page.getByRole('button', { name: /^Ver fontes/ }).getAttribute('aria-expanded'), 'true')
  assert.equal(await page.locator('blockquote').innerText(), quote)
  assert.match(await page.locator('.nlp-source').innerText(), /Fonte alterada/)
  assert.match(await page.locator('.nlp-source').innerText(), /Baixa confiança/)
  assert.match(await page.locator('.nlp-source').innerText(), /Pontuação da extração não disponível/)
  assert.equal(await page.getByRole('link', { name: /Abrir documento na fonte oficial/ }).getAttribute('href'), 'https://www.stj.jus.br/fixture')
  await page.getByText('Versões e rastreabilidade da evidência', { exact: true }).click()
  assert.match(await page.locator('.nlp-source').innerText(), /FX115-T1/)
  await page.getByRole('button', { name: 'Próxima página de fontes' }).click()
  await page.getByRole('button', { name: 'Primeira página de fontes' }).waitFor()
  assert.match(await page.evaluate(() => document.activeElement.textContent), /2 trechos no snapshot/)
  await page.getByRole('button', { name: 'Primeira página de fontes' }).click()
  await page.getByRole('button', { name: 'Próxima página de fontes' }).waitFor()
  await page.getByText('Contexto congelado e integração com PDF', { exact: true }).click()
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Baixar evidências congeladas (JSON)' }).click()
  const download = await downloadPromise
  assert.match(download.suggestedFilename(), /datumlex-evidencias-FX115/)
  assert.match(await page.getByRole('link', { name: /Abrir relatório completo/ }).getAttribute('href'), /FX115-S1\/report\/$/)
  if (process.env.NLP_REPORT_QA_DIR) await page.screenshot({ path: join(process.env.NLP_REPORT_QA_DIR, 'dashboard-desktop.png'), fullPage: true })

  for (const width of [320, 760, 1000, 1440]) {
    await page.setViewportSize({ width, height: 1000 })
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `No horizontal overflow at ${width}`)
  }
  await page.addStyleTag({ content: 'html { font-size:200%; }' })
  await page.setViewportSize({ width: 320, height: 1000 })
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Reflow at enlarged text')
  if (process.env.NLP_REPORT_QA_DIR) await page.screenshot({ path: join(process.env.NLP_REPORT_QA_DIR, 'dashboard-mobile.png') })
  await page.getByRole('button', { name: /^Ver fontes/ }).focus()
  await page.keyboard.press('Space')
  assert.equal(await page.getByRole('button', { name: /^Ver fontes/ }).getAttribute('aria-expanded'), 'false')

  await page.getByLabel('Jurisprudência STJ · liberação por documento', { exact: true }).uncheck()
  await page.getByRole('button', { name: 'Aplicar filtros de NLP', exact: true }).click()
  await page.getByText('Nenhum documento corresponde à seleção nesta população. Ajuste os filtros.').waitFor()
  assert.deepEqual(requests.at(-1).sources, [])
  mode = 'unavailable'
  await page.getByRole('button', { name: 'Restaurar padrões do NLP' }).click()
  await page.getByText(/Análise indisponível: requer fonte autorizada/).waitFor()
  mode = 'error'
  await page.getByRole('button', { name: 'Aplicar filtros de NLP', exact: true }).click()
  await page.getByText('Falha simulada FX115.').waitFor()
  assert.equal(await page.getByRole('heading', { name: group.label }).count(), 0, 'No stale ranking after failure')
  mode = 'ready'
  await page.getByRole('button', { name: 'Tentar novamente' }).click()
  await page.getByRole('heading', { name: group.label }).waitFor()
  mode = 'race'
  await page.getByLabel('Jurisprudência STJ · liberação por documento', { exact: true }).uncheck()
  await page.getByRole('button', { name: 'Aplicar filtros de NLP', exact: true }).click()
  await page.getByRole('button', { name: 'Restaurar padrões do NLP' }).click()
  await page.getByRole('heading', { name: group.label }).waitFor()
  await page.waitForTimeout(350)
  assert.equal(await page.getByRole('heading', { name: group.label }).count(), 1, 'Late responses cannot replace restored context')
  assert.deepEqual(errors, [])
  if (process.env.NLP_REPORT_QA_DIR) {
    const report = await readFile(join(process.env.NLP_REPORT_QA_DIR, 'report.html'), 'utf8')
    const snapshot = JSON.parse(await readFile(join(process.env.NLP_REPORT_QA_DIR, 'report-snapshot.json'), 'utf8'))
    await page.setViewportSize({ width: 1000, height: 1400 })
    await page.setContent(report)
    await page.emulateMedia({ media: 'print' })
    assert.equal(await page.locator('blockquote').count(), snapshot.items.length)
    assert.ok((await page.locator('body').innerText()).includes(snapshot.sha256))
    await page.screenshot({ path: join(process.env.NLP_REPORT_QA_DIR, 'report-preview.png'), fullPage: true })
    const pdf = await page.pdf({ format: 'A4', printBackground: true })
    const parsed = spawnSync(process.env.NLP_QA_PYTHON, ['-B', '-c', 'import sys,io; from pypdf import PdfReader; r=PdfReader(io.BytesIO(sys.stdin.buffer.read())); print("\\n".join(p.extract_text() for p in r.pages))'], { input: pdf, encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
    assert.equal(parsed.status, 0, parsed.stderr)
    for (const expected of [snapshot.sha256, snapshot.query_id, snapshot.items[0].text_version_id, 'Não houve nexo causal.']) assert.ok(parsed.stdout.includes(expected), `PDF preserves ${expected}`)
    console.log('FX115 PDF PASS: actual Django report rendered in Chromium; PDF text matches immutable snapshot hashes, query, text version and exact quote.')
  }
  console.log('FX115-BROWSER-01 PASS: source fidelity, keyboard, versions, filters, empty/error/unavailable/low-confidence, JSON export, responsive 320/760/1000/1440 and enlarged text.')
} catch (error) {
  console.error('Browser errors:', errors, '\nVisible page:', await page.locator('body').innerText())
  throw error
} finally { await browser.close() }
