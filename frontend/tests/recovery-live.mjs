import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { chromium } from '@playwright/test'

const origin = new URL(process.env.FRONTEND_URL || 'http://127.0.0.1:5173')
assert.ok(['localhost', '127.0.0.1'].includes(origin.hostname), 'Use only an isolated local environment')
const secret = process.env.DATUMLEX_SUPPORT_PASSWORD
assert.ok(secret, 'Set the local support password through the environment')
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })
try {
  const context = await browser.newContext({ viewport: { width: 1366, height: 900 } })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  const panel = () => page.waitForResponse((r) => new URL(r.url()).pathname === '/api/research/' && r.ok())
  await page.goto(origin.href)
  await page.getByLabel('E-mail ou CPF').fill('suport')
  await page.getByLabel('Senha', { exact: true }).fill(secret)
  const initialPanel = panel()
  await page.getByRole('button', { name: 'Entrar', exact: true }).click()
  const initial = await (await initialPanel).json()
  assert.ok(initial.scope.cohort)
  assert.ok(initial.metrics.process_records > 0)
  await page.getByRole('heading', { name: 'Síntese da pesquisa' }).waitFor()

  await page.getByRole('button', { name: 'Filtros', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('checkbox', { name: /Indenização por Dano Moral.*10433/ }).waitFor()
  await dialog.getByRole('checkbox', { name: /Responsabilidade Civil.*10431/ }).uncheck()
  await dialog.getByRole('checkbox', { name: /Indenização por Dano Moral.*10433/ }).check()
  const period = dialog.locator('input[type=date]')
  await period.nth(0).fill('2023-01-01')
  const filteredPanel = panel()
  await dialog.getByRole('button', { name: 'Aplicar filtros' }).click()
  const filtered = await (await filteredPanel).json()
  assert.ok(filtered.scope.subject_codes.includes(10433))
  assert.ok(!filtered.scope.subject_codes.includes(10439))
  assert.equal(filtered.scope.start, '2023-01-01')
  const history = filtered.history.reduce((total, row) => total + row.count, 0)
  assert.equal(history, filtered.metrics.process_records)
  assert.ok(history > 0)
  await page.getByText('Histórico por trimestre de ajuizamento', { exact: true }).click()

  for (const [label, magic] of [['Baixar PDF', '%PDF-'], ['Baixar Excel', 'PK']]) {
    await page.getByRole('button', { name: 'Exportar', exact: true }).click()
    const [download] = await Promise.all([
      page.waitForEvent('download'), dialog.getByRole('button', { name: label, exact: true }).click(),
    ])
    assert.equal((await readFile(await download.path())).subarray(0, magic.length).toString(), magic)
    await dialog.waitFor({ state: 'hidden' })
  }

  await page.getByRole('button', { name: 'Acervo por assunto', exact: true }).click()
  await page.getByRole('heading', { name: 'Fontes do recorte' }).waitFor()
  const firstSource = page.locator('.rw-source').first()
  await firstSource.click()
  await dialog.getByRole('link', { name: 'Abrir publicação original' }).waitFor()
  await dialog.getByRole('button', { name: 'Fechar', exact: true }).click()

  await page.getByRole('button', { name: 'Chat da pesquisa', exact: true }).click()
  await page.getByLabel('Sua pergunta').fill('Quais são os indicadores do recorte?')
  const local = page.waitForResponse((r) => r.url().includes('/api/research/chat/') && r.ok())
  await page.getByRole('button', { name: 'Enviar pergunta' }).click()
  assert.equal((await (await local).json()).mode, 'local')
  await page.getByText('DatumLex · Consulta ao acervo', { exact: true }).waitFor()

  await page.setViewportSize({ width: 320, height: 780 })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  assert.deepEqual(errors, [])
  console.log('PASS: real DataJud cohort and source catalogue, date and TPU filters, historical reconciliation, PDF/XLSX, direct chat and mobile.')
} finally {
  await browser.close()
}
