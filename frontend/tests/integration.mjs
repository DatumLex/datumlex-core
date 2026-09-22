import assert from 'node:assert/strict'
import { pathToFileURL } from 'node:url'

const modulePath = process.env.PLAYWRIGHT_MODULE
const { chromium } = await import(modulePath ? pathToFileURL(modulePath).href : 'playwright')
const origin = process.env.FRONTEND_URL || 'http://127.0.0.1:5173'
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const errors = []
page.on('pageerror', (error) => errors.push(error.message))
const status = page.locator('.data-status')
const count = page.locator('.indicator-card--navy strong')
const waitForLoad = () => page.waitForFunction(() => document.querySelector('.indicator-grid')?.getAttribute('aria-busy') === 'false')
const api = async (resource, query = '') => {
  const response = await page.request.get(`${origin}/api/${resource}/${query}`)
  assert.equal(response.status(), 200)
  return response.json()
}

try {
  const all = await api('statistics')
  const { start, end } = all.metadata.available_period
  assert.ok(start && end, 'Real loaded data is required for integration testing')
  await page.goto(origin)
  await waitForLoad()
  assert.equal(await count.innerText(), all.metrics.process_records.toLocaleString('pt-BR'))
  const percent = (value) => value == null ? '—' : new Intl.NumberFormat('pt-BR', { style: 'percent', maximumFractionDigits: 1 }).format(value)
  assert.equal(await page.locator('.indicator-card--green strong').innerText(), percent(all.metrics.grant_rate))
  assert.equal(await page.locator('.indicator-card--gold strong').innerText(), percent(all.metrics.denial_rate))
  assert.match(await status.innerText(), /Amostra parcial/)
  const rows = await page.locator('.instance-row strong').allTextContents()
  assert.equal(rows.reduce((sum, row) => sum + Number(row.replaceAll('.', '')), 0), all.metrics.process_records)
  await page.getByText('Ver dados em tabela', { exact: true }).click()
  assert.ok(await page.getByRole('table').isVisible())
  await page.getByLabel('Ver metodologia de cálculo').click()
  assert.ok(await page.locator('#methodology-popover').isVisible())
  await page.getByLabel('Fechar metodologia').click()

  await page.getByLabel('Data final', { exact: true }).fill(start)
  await page.getByRole('button', { name: 'Aplicar filtros' }).click()
  await waitForLoad()
  const filtered = await api('statistics', `?start=${start}&end=${start}`)
  assert.equal(await count.innerText(), filtered.metrics.process_records.toLocaleString('pt-BR'))
  await page.getByRole('button', { name: 'Limpar filtros' }).click()
  await waitForLoad()
  assert.equal(await count.innerText(), all.metrics.process_records.toLocaleString('pt-BR'))

  await page.getByLabel('Data inicial', { exact: true }).fill(end)
  await page.getByLabel('Data final', { exact: true }).fill(start)
  await page.getByRole('button', { name: 'Aplicar filtros' }).click()
  assert.match(await page.locator('.validation-error').innerText(), /período válido/)
  await page.getByRole('button', { name: 'Limpar filtros' }).click()
  await waitForLoad()

  // Supplement the real-data journey with deterministic empty/error states.
  const emptyHandler = async (route) => {
    const response = await route.fetch()
    const payload = await response.json()
    if (route.request().url().includes('/statistics/')) {
      payload.status = 'empty'
      payload.metrics.process_records = 0
      payload.metrics.distinct_process_numbers = 0
      payload.metrics.grant_rate = null
      payload.metrics.denial_rate = null
      payload.metrics.binary_denominator = 0
      payload.metadata.last_record_refresh = null
    } else payload.series = []
    await route.fulfill({ response, json: payload })
  }
  await page.route('**/api/statistics/**', emptyHandler)
  await page.route('**/api/instances/**', emptyHandler)
  await page.getByRole('button', { name: 'Limpar filtros' }).click()
  await waitForLoad()
  assert.equal(await count.innerText(), '0')
  assert.match(await status.innerText(), /Nenhum registro/)
  assert.equal(await page.locator('.indicator-card--green strong').innerText(), '—')
  await page.unroute('**/api/statistics/**', emptyHandler)
  await page.unroute('**/api/instances/**', emptyHandler)

  const fail = (route) => route.fulfill({ status: 503, contentType: 'application/json', body: '{}' })
  await page.route('**/api/scope/**', fail)
  await page.getByRole('button', { name: 'Limpar filtros' }).click()
  await waitForLoad()
  assert.equal(await count.innerText(), '—')
  assert.match(await status.innerText(), /Não foi possível/)
  await page.unroute('**/api/scope/**', fail)
  await page.getByRole('button', { name: 'Tentar novamente' }).click()
  await waitForLoad()
  assert.equal(await count.innerText(), all.metrics.process_records.toLocaleString('pt-BR'))

  // An old request must never overwrite a later filter selection.
  let release
  const gate = new Promise((resolve) => { release = resolve })
  let began
  const begun = new Promise((resolve) => { began = resolve })
  const delayed = async (route) => {
    const url = new URL(route.request().url())
    if (url.searchParams.get('end') === start) {
      const response = await route.fetch()
      began()
      await gate
      await route.fulfill({ response }).catch(() => {})
    } else await route.continue()
  }
  await page.route('**/api/statistics/**', delayed)
  await page.getByLabel('Data final', { exact: true }).fill(start)
  await page.getByRole('button', { name: 'Aplicar filtros' }).click()
  await begun
  assert.match(await status.innerText(), /Consultando/)
  await page.getByRole('button', { name: 'Limpar filtros' }).click()
  await waitForLoad()
  release()
  await page.waitForTimeout(300)
  assert.equal(await count.innerText(), all.metrics.process_records.toLocaleString('pt-BR'))
  await page.unroute('**/api/statistics/**', delayed)

  if (process.env.SCREENSHOT_PATH) await page.screenshot({ path: process.env.SCREENSHOT_PATH, fullPage: true })
  await page.setViewportSize({ width: 320, height: 900 })
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Mobile layout overflows')
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ result: 'passed', realRecords: all.metrics.process_records, checks: ['API reconciliation', 'dates/apply/reset', 'invalid dates', 'empty', 'error/retry', 'loading', 'stale response', 'mobile', 'accessible table'] }))
} finally {
  await browser.close()
}
