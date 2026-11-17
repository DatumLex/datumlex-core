// Synthetic UI contract; no real Google call or credentials.
import assert from 'node:assert/strict'
import { chromium } from '@playwright/test'
const origin = process.env.FRONTEND_URL || 'http://127.0.0.1:5182'
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage()
const errors = []
page.on('pageerror', error => errors.push(error.message))
let calls = 0
let blocked = false
const draft = { draft_id: 'test-draft', snapshot_id: 'test-snapshot', status: 'draft', sha256: 'test-hash', question: 'Quais fundamentos?',
  facts: [{ evidence_id: 'e1', quote: 'Não houve nexo causal.' }],
  interpretations: [{ text: 'Interpretação a revisar.', evidence_ids: ['e1'] }],
  uncertainties: ['Corpus parcial'], warnings: ['Revisão obrigatória'], sources: [{ id: 'e1', document_id: 'fonte1', revision: 1, text_version_id: 't1', text_sha256: 'hash', passages: ['Não houve nexo causal.'] }],
  usage: { totalTokenCount: 20 }, latency_ms: 100, retrieval: { selected: 1, total: 1 }, model: 'mock', contract_version: 'legal-narrative/1.0' }
await page.route('**/__chat_test__', route => route.fulfill({ contentType: 'text/html', body: `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"></head><body><div id="root"></div><script type="module">
import React from '/node_modules/.vite/deps/react.js';
import ReactDOM from '/node_modules/.vite/deps/react-dom_client.js';
import RefreshRuntime from '/@react-refresh';
RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;
const { default: Chat } = await import('/src/LegalChat.jsx');
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(Chat,{snapshot:{snapshot_id:'test-snapshot',data_mode:'fixture'}}));
</script></body></html>` }))
await page.route('**/api/**', route => {
  const path = new URL(route.request().url()).pathname
  const json = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
  if (path.endsWith('/csrf/')) return json({ csrfToken: 'test' })
  if (path.endsWith('/chat/')) {
    calls++
    return blocked ? json({ error: { message: 'Evidência insuficiente.' } }, 400) : json(draft)
  }
  if (path.endsWith('/test-draft/')) {
    const body = route.request().postDataJSON()
    assert.equal(body.confirmed, true)
    assert.equal(body.expected_sha256, 'test-hash')
    return json({ ...draft, status: 'approved', user_conclusions: body.conclusions, approved_at: new Date().toISOString() })
  }
  return json({})
})
try {
  await page.goto(`${origin}/__chat_test__`)
  const send = page.getByRole('button', { name: 'Enviar pergunta', exact: true })
  await send.waitFor()
  assert.equal(await send.isDisabled(), true)
  await page.getByLabel(/Autorizo o envio/).check()
  await send.click()
  await page.getByText('Versão 1 · Rascunho', { exact: false }).waitFor()
  assert.equal(calls, 1)
  assert.equal(await page.getByRole('link', { name: /Baixar análise/ }).count(), 0)
  await page.getByText('Inspecionar fontes', { exact: false }).click()
  await page.getByText('fonte1', { exact: true }).waitFor()
  const approve = page.getByRole('button', { name: 'Aprovar versão revisada' })
  assert.equal(await approve.isDisabled(), true)
  await page.getByLabel(/Suas conclusões/).fill('Ação, órgão, interpretação própria.')
  await page.getByLabel(/Revisei os trechos/).check()
  await approve.click()
  await page.getByRole('link', { name: /Baixar análise aprovada/ }).waitFor()
  await page.getByText('Ação, órgão, interpretação própria.', { exact: true }).waitFor()
  blocked = true
  await send.click()
  await page.getByRole('alert').filter({ hasText: 'Evidência insuficiente.' }).waitFor()
  assert.deepEqual(errors, [])
  console.log('Chat UI passed: consent, source inspection, approval gate, UTF-8 and safe failure.')
} finally { await browser.close() }
