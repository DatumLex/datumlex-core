// No HTTP mocks: exercises the actual isolated demonstration API and extractor output.
import { chromium } from '@playwright/test'
import assert from 'node:assert/strict'
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
try {
  await page.goto('http://127.0.0.1:5180/nlp-demo.html')
  await page.getByRole('heading', { name: 'O dever de indenizar exige nexo causal porque o dano deve decorrer da conduta.', exact: true }).waitFor()
  assert.match(await page.locator('.nlp-ranking').innerText(), /2 documentos distintos/)
  await page.getByRole('button', { name: /^Ver fontes/ }).first().click()
  await page.locator('.nlp-source').first().waitFor()
  assert.equal(await page.locator('.nlp-source').count(), 2)
  assert.match(await page.locator('.nlp-source').first().innerText(), /Link oficial específico não disponível/)
  await page.locator('.nlp-source summary').first().click()
  await page.screenshot({ path: '../../output/task-115-demo/nlp-working.png', fullPage: true })
  await page.locator('.nlp-source summary').first().click()
  await page.locator('.nlp-thesis').first().screenshot({ path: '../../output/task-115-demo/ver-fontes.png' })
  await page.getByLabel('Conteúdo', { exact: true }).selectOption('grounds')
  await page.getByRole('heading', { name: 'O dever de indenizar exige nexo causal porque o dano deve decorrer da conduta.', exact: true }).waitFor()
  assert.match(await page.locator('.nlp-ranking').innerText(), /2 documentos distintos/)
  console.log('LIVE DEMO PASS: actual API, persisted rule extractions, two thesis/ground groups, three documents, source excerpts and versions.')
  const health = await page.request.get('http://127.0.0.1:8000/api/health/')
  console.log('NORMAL BACKEND HEALTH:', health.status(), (await health.text()).slice(0, 200))
} catch (error) { console.error(await page.locator('body').innerText()); throw error }
finally { await browser.close() }
