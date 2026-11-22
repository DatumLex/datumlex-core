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
  await page.getByRole('heading', { name: 'Pesquisa processual' }).waitFor()
  return data
}
async function logout() {
  await nav('Sair da conta').click()
  await page.getByRole('heading', { name: 'Bem-vindo ao DatumLex' }).waitFor()
  assert.equal((await context.request.get(origin + '/api/auth/me/')).status(), 401)
}
async function inspectExports(expected) {
  for (const [button, format] of [['Síntese em PDF', 'pdf'], ['Síntese em Excel', 'xlsx'], ['Registros DataJud em Excel', 'records']]) {
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
  if sys.argv[1] == 'records':
   rows=values(1)
   assert len(rows) == int(sys.argv[2])+1
   assert rows[0] == ['Número CNJ', 'Tribunal', 'Classe', 'Grau', 'Órgão', 'Ajuizamento', 'Resultado']
   assert all(row[1]=='TJDFT' and row[3]=='G2' for row in rows[1:])
   assert dict(values(2))['Assuntos CNJ selecionados']=='10433'
   sys.exit(0)
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

const applyButton = () => dialog.getByRole('button', { name: 'Aplicar filtros' })
async function filter(change) {
  await nav('Filtros').click()
  await change()
  const changed = response('/api/research/')
  await applyButton().click()
  return (await changed).json()
}
const tpu = (code) => dialog.getByRole('checkbox', { name: new RegExp(`\\(${code} ·`) })
const compare = (data, ref) => {
  for (const key of ['process_records', 'distinct_process_numbers', 'binary_denominator', 'granted', 'denied', 'excluded']) {
    assert.deepEqual(data.metrics[key], ref[key], key)
  }
  for (const [key, value] of Object.entries(data.merit_baseline)) assert.deepEqual(value, ref.baseline[key], key)
  assert.deepEqual(data.history, ref.history)
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
    for (const [label, title] of [['Jurisprudência', 'Jurisprudência sintética 4A'], ['Precedentes', 'Precedente sintético 4A'], ['Doutrina', 'Doutrina sintética 4A']]) {
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
    await page.getByRole('heading', { name: 'Pesquisa processual' }).waitFor()
    await nav('Fontes e cobertura').click()
    await page.getByText(/75 de 170 células tribunal\/ano/).waitFor()
    const tst = page.locator('details').filter({ has: page.getByText('TST · Sem registros no lote', { exact: true }) })
    await tst.locator('summary').click()
    await tst.getByText('2010 · Sem registros no lote · cobertura não verificada').waitFor()
    await nav('Pesquisa').click()
    const history4b = JSON.parse(await readFile(new URL('DATUMLEX_4B_HISTORICO.json', recovery), 'utf8'))
    const baseline = history4b.results.datumlex_restore
    compare(initial, baseline.all)
    await page.getByText('25 de 269 providos (9,3%)', { exact: true }).waitFor()
    const isBefore = await page.evaluate(() => Boolean(
      document.querySelector('#rw-process-title').compareDocumentPosition(document.querySelector('.rw-synthesis h2'))
      & Node.DOCUMENT_POSITION_FOLLOWING
    ))
    assert.ok(isBefore)
    await nav('Próxima').click()
    await page.getByText('Página 2', { exact: true }).waitFor()

    await nav('Análise detalhada').click()
    const legacyCount = history4b.results.datumlex_ops_f3_full.legacy_10431
    await page.getByText(`${legacyCount} registros`, { exact: true }).waitFor()
    await page.getByText('Assunto CNJ ativo 10431.', { exact: false }).waitFor()
    await page.getByRole('button', { name: 'Exportar registros da análise (Excel)' }).waitFor()
    const legacyFilters = page.getByRole('form', { name: 'Filtros do dashboard' })
    await legacyFilters.getByLabel('Data inicial').fill('2023-01-01')
    await legacyFilters.getByLabel('Data final').fill('2023-12-31')
    const legacyUpdated = response('/api/statistics/')
    await legacyFilters.getByRole('button', { name: 'Aplicar filtros' }).click()
    const legacyStats = await (await legacyUpdated).json()
    assert.equal(legacyStats.metadata.scope.start, '2023-01-01')
    assert.equal(legacyStats.metadata.scope.end, '2023-12-31')
    await page.getByText(/no período de 01\/01\/2023 a 31\/12\/2023/).waitFor()
    await nav('Pesquisa').click()

    compare(await filter(() => dialog.getByRole('checkbox', { name: 'Acidentes de trânsito' }).check()), baseline.editorial_transito)
    const inTransit = await filter(async () => {
      await tpu(10431).uncheck()
      await dialog.getByLabel('Localizar assunto TPU').fill('10435')
      await tpu(10435).check()
    })
    compare(inTransit, baseline.transito_10435)
    const onlyMaterial = await filter(async () => {
      await tpu(10435).uncheck()
      await dialog.getByLabel('Localizar assunto TPU').fill('10441')
      await tpu(10441).check()
    })
    compare(onlyMaterial, baseline.transito_10441)
    const transitUnion = await filter(async () => {
      await dialog.getByLabel('Localizar assunto TPU').fill('10435')
      await tpu(10435).check()
    })
    compare(transitUnion, baseline.transito_uniao)
    await page.getByText('0 de 3 providos (0%)', { exact: true }).waitFor()
    await page.getByText('10435, 10441', { exact: true }).waitFor()
    const combinedTransit = await filter(async () => {
      const courts = dialog.getByRole('group', { name: 'Tribunais autorizados' })
      for (const item of await courts.getByRole('checkbox').all()) {
        if (!await item.evaluate(el => el.parentElement.textContent.trim() === 'TJDFT')) await item.uncheck()
      }
      await dialog.getByRole('checkbox', { name: '2ª instância' }).check()
      await dialog.locator('input[type=date]').nth(0).fill('2019-01-01')
      await dialog.locator('input[type=date]').nth(1).fill('2025-12-31')
    })
    compare(combinedTransit, baseline.tjdf_g2_transito)
    await page.getByText('Sem documentos elegíveis para calcular a taxa.', { exact: true }).waitFor()

    compare(await filter(async () => {
      await dialog.getByRole('button', { name: 'Restaurar filtros' }).click()
      await dialog.getByRole('checkbox', { name: 'Responsabilidade em serviços de saúde' }).check()
    }), baseline.editorial_saude)
    compare(await filter(async () => {
      await tpu(10431).uncheck()
      await dialog.getByLabel('Localizar assunto TPU').fill('10434')
      await tpu(10434).check()
    }), baseline.saude_10434)
    compare(await filter(async () => {
      await tpu(10434).uncheck()
      await dialog.getByLabel('Localizar assunto TPU').fill('10440')
      await tpu(10440).check()
    }), baseline.saude_10440)
    compare(await filter(async () => {
      await dialog.getByLabel('Localizar assunto TPU').fill('10434')
      await tpu(10434).check()
    }), baseline.saude_uniao)
    compare(await filter(async () => {
      await dialog.locator('summary').getByText('Resultados do DataJud', { exact: true }).click()
      await dialog.getByRole('checkbox', { name: 'Desprovido', exact: true }).uncheck()
    }), baseline.saude_sem_desprovido)
    await page.getByText(/O filtro de resultado mostra 31 documentos de 38/).waitFor()
    await page.getByText('0 de 7 providos (0%)', { exact: true }).waitFor()

    await nav('Filtros').click()
    await dialog.getByRole('button', { name: 'Restaurar filtros' }).click()
    const courts = dialog.getByRole('group', { name: 'Tribunais autorizados' })
    for (const item of await courts.getByRole('checkbox').all()) {
      if (!await item.evaluate(el => el.parentElement.textContent.trim() === 'TJDFT')) await item.uncheck()
    }
    await dialog.getByRole('checkbox', { name: /Responsabilidade Civil.*10431/ }).uncheck()
    await dialog.getByLabel('Localizar assunto TPU').fill('10433')
    await tpu(10433).check()
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
    compare(filtered, baseline.tjdf_g2_2023)
    await page.getByText('Histórico por trimestre de ajuizamento', { exact: true }).click()
    const row = page.locator('.rw-process-row').first()
    await row.locator('summary').click()
    await row.getByText('Órgão julgador', { exact: true }).waitFor()
    const identifier = await row.locator('summary > span').innerText()
    const cnjRequest = response('/api/research/')
    await page.getByLabel('Número CNJ exato').fill(identifier)
    await nav('Consultar processo').click()
    assert.equal((await (await cnjRequest).json()).metrics.distinct_process_numbers, 1)
    const restored = response('/api/research/')
    await nav('Limpar número CNJ').click()
    await restored
    await inspectExports(filtered)

    await nav('Acervo por assunto').click()
    for (const label of ['Jurisprudência', 'Precedentes', 'Doutrina']) {
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
    await page.setViewportSize({ width: 390, height: 844 })
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    await page.getByLabel('Seção', { exact: true }).selectOption('search')
    await nav('Filtros').click()
    const applyBox = await applyButton().boundingBox()
    assert.ok(applyBox.y >= 0 && applyBox.y + applyBox.height <= 844)
    await dialog.getByLabel('Localizar assunto TPU').fill('saude')
    await tpu(10440).waitFor()
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
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
      profiles: 2, pending: 8, downloads: ['summary.pdf', 'summary.xlsx', 'records.xlsx'], legacy_10431: legacyCount, scenarios: history4b.equal.length, mobile_width: 390, retry: true, page_errors: errors }))
  }
  assert.deepEqual(errors, [])
} finally {
  await browser.close()
}
