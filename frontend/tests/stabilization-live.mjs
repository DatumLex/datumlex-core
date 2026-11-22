import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { chromium } from '@playwright/test'

const origin = 'http://127.0.0.1:5173'
const recovery = new URL('../../../recuperacao/', import.meta.url)
const fixture = process.env.DATUMLEX_4A_SYNTHETIC === '1'
const readSecret = async (name) => (await readFile(new URL(name, recovery), 'utf8')).trim()
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1366, height: 900 } })
const page = await context.newPage()
page.setDefaultTimeout(9000)
const errors = []
page.on('pageerror', error => errors.push(error.message))
const dialog = page.getByRole('dialog')
const nav = (name) => page.getByRole('button', { name, exact: true })
const response = (path) => page.waitForResponse(r => new URL(r.url()).pathname === path && r.ok())
const cohort = 'civil-2010-sgt-2026-11'
async function login(id, secret) {
  await page.goto(origin)
  await page.getByLabel('E-mail ou CPF').fill(id)
  await page.getByLabel('Senha', { exact: true }).fill(secret)
  const authenticated = response('/api/auth/login/')
  const panel = response('/api/research/')
  await nav('Entrar').click()
  assert.equal((await authenticated).status(), 200)
  const data = await (await panel).json()
  await page.getByRole('heading', { name: 'Painel de pesquisa' }).waitFor()
  return data
}
async function logout() {
  await nav('Sair da conta').click()
  await page.getByRole('heading', { name: 'Bem-vindo ao DatumLex' }).waitFor()
  assert.equal((await context.request.get(origin + '/api/auth/me/')).status(), 401)
}
async function inspectExports(expected) {
  for (const [button, format] of [['Baixar PDF', 'pdf'], ['Baixar Excel', 'xlsx']]) {
    await nav('Exportar').click()
    const [download] = await Promise.all([page.waitForEvent('download'), dialog.getByRole('button', { name: button }).click()])
    const content = await readFile(await download.path())
    const script = `
import sys, io, zipfile
from xml.etree import ElementTree as ET
raw = sys.stdin.buffer.read()
if sys.argv[1] == 'pdf':
 from pypdf import PdfReader
 text = ' '.join(page.extract_text() for page in PdfReader(io.BytesIO(raw)).pages)
 assert all(x in text for x in ('10433','G2','2023-01-01','2023-12-31'))
 assert 'Revisão pendente' not in text
else:
 with zipfile.ZipFile(io.BytesIO(raw)) as book:
  def values(n):
   root=ET.fromstring(book.read('xl/worksheets/sheet%d.xml' % n))
   return [[el.text for el in row.iter() if el.tag.rsplit('}',1)[-1] in ('v','t')]
           for row in root.iter() if row.tag.rsplit('}',1)[-1]=='row']
  scope = dict(values(1))
  metrics = dict(values(4))
  assert all(value in scope[key] for key,value in [('Assuntos CNJ','10433'),('Graus DataJud','G2'),('Período','2023-01-01')])
  assert metrics['Registros DataJud'] == sys.argv[2]
  assert metrics['Resultados integrais antes do filtro de resultado'] == sys.argv[3]
  assert len(values(3)) == 1
`
    const checked = spawnSync(fileURLToPath(new URL('runtime/bin/python', recovery)), ['-c', script, format,
      String(expected.metrics.process_records), String(expected.merit_baseline.binary_denominator)], { input: content })
    assert.equal(checked.status, 0, checked.stderr.toString())
    await dialog.waitFor({ state: 'hidden' })
  }
}

try {
  const initial = await login('datumlex-4a-reader@example.test', await readSecret('reader-ops-4a.local'))
  assert.equal(initial.scope.cohort, cohort)
  assert.equal(initial.metrics.process_records, 4518)
  assert.equal(initial.metrics.distinct_process_numbers, 4516)
  assert.equal(initial.metrics.binary_denominator, 269)
  assert.equal(initial.provider, 'local')
  assert.equal(await nav('Usuários').count(), 0)
  assert.equal((await context.request.get(origin + '/api/corpus/review/')).status(), 403)
  if (fixture) {
    await nav('Acervo por assunto').click()
    for (const [label, title] of [['Decisões', 'Jurisprudência sintética 4A'], ['Precedentes', 'Precedente sintético 4A'], ['Doutrina', 'Doutrina sintética 4A']]) {
      await nav(label).click()
      await page.getByRole('button', { name: new RegExp(title) }).click()
      await dialog.getByRole('link', { name: 'Abrir publicação original' }).waitFor()
      await dialog.getByRole('button', { name: 'Fechar', exact: true }).click()
    }
    await logout()
    console.log('Chrome: três categorias aprovadas sintéticas e detalhes autorizados.')
  } else {
    assert.deepEqual(initial.counts, { jurisprudence: 0, precedent: 0, doctrine: 0 })
    await page.reload()
    await page.getByRole('heading', { name: 'Painel de pesquisa' }).waitFor()
    await nav('Fontes e cobertura').click()
    await page.getByText(/75 de 170 células tribunal\/ano/).waitFor()
    const tst = page.locator('details').filter({ has: page.getByText('TST · Sem registros no lote', { exact: true }) })
    await tst.locator('summary').click()
    await tst.getByText('2010 · Sem registros no lote · cobertura não verificada').waitFor()
    await nav('Pesquisa').click()
    await nav('Filtros').click()
    const courts = dialog.getByRole('group', { name: 'Tribunais autorizados' })
    for (const item of await courts.getByRole('checkbox').all()) {
      if (!await item.evaluate(el => el.parentElement.textContent.trim() === 'TJDFT')) await item.uncheck()
    }
    await dialog.getByRole('checkbox', { name: /Responsabilidade Civil.*10431/ }).uncheck()
    await dialog.getByRole('checkbox', { name: /Indenização por Dano Moral.*10433/ }).check()
    await dialog.getByRole('checkbox', { name: '2ª instância' }).check()
    await dialog.locator('input[type=date]').nth(0).fill('2023-01-01')
    await dialog.locator('input[type=date]').nth(1).fill('2023-12-31')
    const applied = response('/api/research/')
    await dialog.getByRole('button', { name: 'Aplicar filtros' }).click()
    const filtered = await (await applied).json()
    assert.equal(filtered.scope.court, 'TJDFT')
    assert.deepEqual(filtered.scope.degree, ['G2'])
    assert.ok(filtered.scope.subject_codes.includes(10433) && !filtered.scope.subject_codes.includes(10439))
    assert.equal(filtered.scope.end, '2023-12-31')
    assert.ok(filtered.metrics.process_records > 0)
    assert.equal(filtered.history.reduce((n, row) => n + row.count, 0), filtered.metrics.process_records)
    const historic = JSON.parse(await readFile(new URL('DATUMLEX_4A_HISTORICO.json', recovery), 'utf8'))
    for (const [data, reference] of [[initial, historic.all], [filtered, historic.filtered]]) {
      for (const field of ['process_records', 'distinct_process_numbers', 'binary_denominator', 'granted', 'denied']) {
        assert.equal(data.metrics[field], reference[field], field)
      }
    }
    await page.getByText('Histórico por trimestre de ajuizamento', { exact: true }).click()
    await nav('Consultar processos do recorte').click()
    await dialog.locator('details summary').first().click()
    await dialog.locator('details[open]').getByText(/Ajuizamento .*2ª instância/).waitFor()
    await dialog.getByRole('button', { name: 'Fechar', exact: true }).click()
    await inspectExports(filtered)

    await nav('Acervo por assunto').click()
    for (const label of ['Decisões', 'Precedentes', 'Doutrina']) {
      const loaded = response('/api/research/sources/')
      await nav(label).click()
      const result = await loaded
      assert.equal((await result.json()).total, 0)
      assert.equal(new URL(result.url()).searchParams.get('degree'), 'G2')
      await page.getByText('Nenhuma fonte aprovada neste recorte.').waitFor()
    }
    await nav('Precedentes e teses').click()
    await page.getByText('Sem precedentes ou vínculos disponíveis no recorte.').waitFor()
    await nav('Chat da pesquisa').click()
    await page.getByLabel('Sua pergunta').fill('Como foi calculada a taxa de provimento?')
    const answered = response('/api/research/chat/')
    await nav('Enviar pergunta').click()
    const chat = await answered
    const answer = await chat.json()
    assert.equal(new URL(chat.url()).searchParams.get('start'), '2023-01-01')
    assert.equal(new URL(chat.url()).searchParams.get('degree'), 'G2')
    assert.equal(answer.mode, 'local')
    assert.deepEqual(answer.sources, [])
    const blocks = answer.paragraphs.map(row => row.text).join(' ')
    assert.ok(blocks.includes(filtered.metrics.process_records.toLocaleString('pt-BR') + ' registros'))
    if (filtered.merit_baseline.binary_denominator) {
      assert.ok(blocks.includes(filtered.merit_baseline.binary_denominator.toLocaleString('pt-BR') + ' resultados elegíveis'))
    }
    await page.setViewportSize({ width: 320, height: 780 })
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))

    await nav('Pesquisa').click()
    await nav('Filtros').click()
    await dialog.getByRole('button', { name: 'Restaurar filtros' }).click()
    await page.route('**/api/research/?*', route => route.fulfill({ status: 503, body: '{}' }))
    await dialog.getByRole('button', { name: 'Aplicar filtros' }).click()
    await nav('Tentar novamente').waitFor()
    await page.unroute('**/api/research/?*')
    const retried = response('/api/research/')
    await nav('Tentar novamente').click()
    assert.equal((await (await retried).json()).metrics.process_records, 4518)
    await logout()

    const master = await login('suport', await readSecret('support-ops-4a.local'))
    assert.deepEqual(master.counts, initial.counts)
    await nav('Usuários').waitFor()
    const review = await context.request.get(origin + '/api/corpus/review/')
    assert.equal(review.status(), 200)
    const { items } = await review.json()
    assert.equal(items.length, 8)
    assert.ok(items.every(item => item.review_status === 'pending'))
    for (const { id } of items) {
      assert.equal((await context.request.get(origin + `/api/corpus/review/${id}/`)).status(), 200)
      assert.equal((await context.request.get(origin + `/api/corpus/${id}/`)).status(), 404)
    }
    await logout()
    await login('datumlex-4a-reader@example.test', await readSecret('reader-ops-4a.local'))
    for (const { id } of items) {
      assert.equal((await context.request.get(origin + `/api/corpus/${id}/`)).status(), 404)
      assert.equal((await context.request.get(origin + `/api/corpus/review/${id}/`)).status(), 403)
    }
    await logout()
    console.log(JSON.stringify({ browser: 'Chrome', facts: 4518, distinct: 4516, denominator: 269,
      filtered: filtered.metrics.process_records, filtered_denominator: filtered.merit_baseline.binary_denominator,
      profiles: 2, pending: 8, downloads: ['pdf', 'xlsx'], mobile_width: 320, retry: true, page_errors: errors }))
  }
  assert.deepEqual(errors, [])
} finally {
  await browser.close()
}
