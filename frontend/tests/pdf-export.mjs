// Synthetic browser fixtures only; no real credentials or database access.
import assert from 'node:assert/strict'
import { chromium } from '@playwright/test'

const origin = process.env.FRONTEND_URL || 'http://127.0.0.1:5182'
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ acceptDownloads: true })
let reportQuery
let failure = false
const errors = []
page.on('pageerror', error => errors.push(error.message))
await page.route('**/__pdf_test__', route => route.fulfill({ contentType: 'text/html', body: `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"></head><body><div id="root"></div><script type="module">
import React from '/node_modules/.vite/deps/react.js';
import ReactDOM from '/node_modules/.vite/deps/react-dom_client.js';
import RefreshRuntime from '/@react-refresh';
RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;
const { default: App } = await import('/src/App.jsx');
import '/src/index.css';
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App,{court:'STJ',courts:['STJ']}));
</script></body></html>` }))
await page.route('**/api/**', route => {
  const url = new URL(route.request().url())
  const json = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
  const scope = { court: 'STJ', subject: null, start: url.searchParams.get('start') || '2016-01-01', end: url.searchParams.get('end') || '2026-10-25' }
  const metadata = { scope, available_period: { start: '2016-01-01', end: '2026-10-25' }, source: 'Synthetic fixture', latest_run: null }
  if (url.pathname.endsWith('/report.pdf/')) {
    reportQuery = url.searchParams
    return failure ? json({ error: { message: 'Exportação bloqueada na fixture.' } }, 403) : route.fulfill({ contentType: 'application/pdf', body: '%PDF-1.4\n% synthetic transport fixture\n%%EOF' })
  }
  if (url.pathname.endsWith('/scope/')) return json({ metadata, subjects: [] })
  if (url.pathname.endsWith('/statistics/')) return json({ status: 'partial', metadata, metrics: { process_records: 3, distinct_process_numbers: 3, granted: 1, denied: 2, binary_denominator: 3, grant_rate: 1 / 3, denial_rate: 2 / 3, excluded: {} } })
  if (url.pathname.endsWith('/instances/')) return json({ metadata, series: [{ time__year: 2016, time__quarter: 1, degree: 'SUP', count: 3 }] })
  if (url.pathname.endsWith('/distribution/')) return json({ metadata, series: [], denominator: 3, excluded: {} })
  return json({ error: { message: 'NLP fixture not loaded' } }, 503)
})
try {
  await page.goto(`${origin}/__pdf_test__`)
  const button = page.getByRole('button', { name: 'Exportar resumo em PDF' })
  await button.waitFor()
  await page.waitForFunction(() => !document.querySelector('.filter-actions button:last-child').disabled)
  await page.getByLabel('Data inicial').fill('2017-01-01')
  const downloaded = page.waitForEvent('download')
  await button.click()
  const download = await downloaded
  assert.equal(download.suggestedFilename(), 'datumlex-2016-01-01-2026-10-25.pdf')
  assert.equal(reportQuery.get('start'), '2016-01-01', 'Unapplied draft must not affect the PDF')
  assert.equal(reportQuery.get('court'), 'STJ')
  await page.getByRole('button', { name: 'Aplicar filtros' }).click()
  await page.waitForFunction(() => !document.querySelector('.filter-actions button:last-child').disabled)
  const second = page.waitForEvent('download')
  await button.click()
  await second
  assert.equal(reportQuery.get('start'), '2017-01-01')
  failure = true
  await button.click()
  await page.getByRole('alert').filter({ hasText: 'Exportação bloqueada na fixture.' }).waitFor()
  assert.deepEqual(errors, [])
  console.log('PDF browser checks passed: download, applied filters, draft isolation and failure feedback.')
} finally {
  await browser.close()
}
