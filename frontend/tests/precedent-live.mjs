import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { chromium } from '@playwright/test'

const recovery = new URL('../../../recuperacao/', import.meta.url)
const origin = 'http://127.0.0.1:5173'
const fixture = process.env.DATUMLEX_SYNTHETIC_PRECEDENT_ID
const pendingIds = (process.env.DATUMLEX_PENDING_CORPUS_IDS || '').split(',')
assert.match(fixture || '', /^[0-9]+$/)
assert.equal(pendingIds.length, 8)
assert.ok(pendingIds.every(id => /^[0-9]+$/.test(id)))
const browser = await chromium.launch({ channel: 'chrome', headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1366, height: 900 } })
  page.setDefaultTimeout(9000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(origin)
  await page.getByLabel('E-mail ou CPF').fill('datumlex-4a-reader@example.test')
  const secret = (await readFile(new URL('reader-ops-4a.local', recovery), 'utf8')).trim()
  await page.getByLabel('Senha', { exact: true }).fill(secret)
  await page.getByRole('button', { name: 'Entrar', exact: true }).click()
  await page.getByRole('button', { name: 'Buscar precedentes', exact: true }).click()

  const search = async (term) => {
    await page.getByLabel('Título ou identificador').fill(term)
    const response = page.waitForResponse(r => {
      const url = new URL(r.url())
      return url.pathname === '/api/research/sources/' && url.searchParams.get('q') === term
    })
    await page.getByRole('button', { name: 'Buscar', exact: true }).click()
    const result = await response
    assert.equal(result.status(), 200)
    return (await result.json()).items
  }

  const allDates = page.getByRole('checkbox', { name: 'Buscar precedentes em todas as datas' })
  await allDates.uncheck()
  assert.deepEqual(await search('Súmula 37'), [])
  await allDates.check()
  const matches = await search('Súmula 37')
  assert.deepEqual(matches.map(item => item.id), [`F${fixture}`])
  await page.getByRole('button', { name: /Súmula · STJ.*Súmula 37 · Referência sintética 4C/ }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByText('Súmula · STJ · Colegiado sintético').waitFor()
  await dialog.getByText(/Conferida em/).waitFor()
  await dialog.getByText(/Assuntos editoriais · Dano moral/).waitFor()
  await dialog.getByText(/A ficha exibe metadados e link/).waitFor()
  const original = dialog.getByRole('link', { name: 'Abrir publicação original' })
  const syntheticUrl = origin + '/api/health/'
  assert.equal(await original.getAttribute('href'), syntheticUrl)
  const opened = page.waitForEvent('popup')
  await original.click()
  const popup = await opened
  await popup.waitForURL(syntheticUrl, { timeout: 9000 })
  await popup.close()
  assert.equal(await dialog.getByText('Trecho sintético retido').count(), 0)
  const detail = await page.request.get(`${origin}/api/corpus/${fixture}/`)
  assert.equal((await detail.json()).excerpt, '')
  await dialog.getByRole('button', { name: 'Fechar', exact: true }).click()
  assert.deepEqual(await search('Tema 1111'), [])
  for (const pending of pendingIds) {
    assert.equal((await page.request.get(`${origin}/api/corpus/${pending}/`)).status(), 404)
  }
  assert.deepEqual(errors, [])
  console.log('Chrome: busca de 1992, ficha, link, separação de trecho e oito fontes pendentes invisíveis.')
} finally {
  await browser.close()
}
