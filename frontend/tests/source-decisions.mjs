// Synthetic sources; no legal assertions or database writes.
import assert from 'node:assert/strict'
import { chromium } from '@playwright/test'

const origin = process.env.FRONTEND_URL || 'http://127.0.0.1:5182'
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1100, height: 900 } })
await page.route('**/__source_test__', route => route.fulfill({ contentType: 'text/html', body: `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"></head><body><div id="root"></div><script type="module">
import React from '/node_modules/.vite/deps/react.js';
import ReactDOM from '/node_modules/.vite/deps/react-dom_client.js';
import RefreshRuntime from '/@react-refresh';
RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;
const { default: SourceDecisions } = await import('/src/SourceDecisions.jsx');
import '/src/index.css';
const refs=[{identifier:'theme-1',title:'Tema de teste',source_url:'https://pangeabnp.pdpj.jus.br/pesquisa?nr=1',related_decisions:[{identifier:'REsp 123/DF',url:'https://www.stj.jus.br/processo',locator:'processosParadigma[0]'},{identifier:'REsp 123/DF',url:'https://www.stj.jus.br/processo'},{identifier:'REsp 456/SP',url:'javascript:alert(1)'}]}];
const root=ReactDOM.createRoot(document.getElementById('root'));
window.showSources=(selection)=>root.render(React.createElement(SourceDecisions,{references:refs,selectedIdentifiers:selection ? new Set(selection) : null}));
window.showSources();
</script></body></html>` }))
try {
  await page.goto(`${origin}/__source_test__`)
  await page.getByRole('heading', { name: 'Processos citados pela fonte' }).waitFor()
  assert.equal(await page.locator('.related-item').count(), 2)
  for (const width of [320, 760, 1100]) {
    await page.setViewportSize({ width, height: 900 })
    const card = await page.locator('.source-citation-item').first().boundingBox()
    const content = await page.locator('.source-citation-content').first().boundingBox()
    assert.ok(content.width >= card.width - 40, `Citation content must fill the card at ${width}px`)
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
  }
  assert.equal(await page.getByRole('link', { name: 'Consultar processo no STJ' }).count(), 1)
  assert.equal(await page.locator('a[href^="javascript:"]').count(), 0)
  await page.getByText('Link específico do processo não disponibilizado.').waitFor()
  await page.getByText('Como interpretar estas citações', { exact: true }).click()
  assert.match(await page.locator('.source-citations').innerText(), /não comprova relação/)
  await page.getByText('Como interpretar estas citações', { exact: true }).click()
  if (process.env.SCREENSHOT_PATH) await page.screenshot({ path: process.env.SCREENSHOT_PATH, fullPage: true })
  await page.evaluate(() => window.showSources(['other-theme']))
  await page.getByText(/Nenhum processo citado nas referências/).waitFor()
  assert.equal(await page.locator('.related-item').count(), 0)
  await page.evaluate(() => window.showSources(['theme-1']))
  await page.getByRole('heading', { name: 'REsp 123/DF' }).waitFor()
  console.log('Source decisions checks passed: citations without local links, deduplication, selection and safe URLs.')
} finally { await browser.close() }
