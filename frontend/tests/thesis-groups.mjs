import assert from 'node:assert/strict'
import { chromium } from '@playwright/test'
const browser = await chromium.launch({channel:'msedge',headless:true})
const page = await browser.newPage({viewport:{width:1440,height:1050}})
const errors=[]
page.on('pageerror', error=>errors.push(error.message))
await page.route('**/__thesis_test__', route=>route.fulfill({contentType:'text/html',body:`<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"></head><body><div id="root"></div><script type="module">
import React from '/node_modules/.vite/deps/react.js';
import ReactDOM from '/node_modules/.vite/deps/react-dom_client.js';
import RefreshRuntime from '/@react-refresh';
RefreshRuntime.injectIntoGlobalHook(window);window.$RefreshReg$=()=>{};window.$RefreshSig$=()=>type=>type;window.__vite_plugin_react_preamble_installed__=true;
const {default:ThesisGroups}=await import('/src/ThesisGroups.jsx');
const {default:SourceReferences}=await import('/src/SourceReferences.jsx');
import '/src/index.css';
const labels=['Responsabilidade objetiva','Nexo causal','Dano moral','Culpa exclusiva'];
const groups=labels.map((label,i)=>({id:String(i),label,title:label+' — enunciado ilustrativo para validar a apresentação da interface.',case_count:[312,247,198,141][i],approved:false,source_references:[{identifier:'FONTE-TESTE-'+i,source_institution:i%2?'TJDFT':'STJ',source_url:i===3?'javascript:alert(1)':'https://www.stj.jus.br/'}]}));
groups[0].label=groups[0].title='A abstenção da inscrição/manutenção em cadastro de inadimplentes, requerida em antecipação de tutela e/ou medida cautelar, somente será deferida se demonstrados os requisitos. O texto integral permanece disponível para consulta.';
const references=[{identifier:'FONTE-TESTE-0',title:'Referência de teste com metadados complementares',source_locator:'Trecho 1'},{identifier:'extra',thesis:groups[1].title,source_url:'https://pangeabnp.pdpj.jus.br/pesquisa',source_institution:'Pangea'}];
function Demo(){const [selectedId,setSelected]=React.useState(null);return React.createElement('main',{className:'dashboard'},React.createElement('header',null,React.createElement('span',{className:'eyebrow'},'DatumLex · prévia de interface'),React.createElement('h1',null,'Responsabilidade Civil — TJDFT × STJ'),React.createElement('p',null,'Dados sintéticos para teste visual. As fontes abaixo não fundamentam teses jurídicas.')),React.createElement('section',{className:'tab-content'},React.createElement('span',{className:'eyebrow'},'Teses e rastreabilidade'),React.createElement('h2',null,'Principais teses no recorte'),React.createElement('p',null,'Títulos curtos · resumos expansíveis · fontes nas decisões relacionadas.'),React.createElement('div',{className:'precedent-grid'},React.createElement('article',{className:'thesis-card'},React.createElement(ThesisGroups,{groups,selectedId,onSelect:id=>setSelected(current=>current===id?null:id)})),React.createElement('article',{className:'related-card'},React.createElement('h3',null,'Decisões relacionadas'),React.createElement(SourceReferences,{groups,references,selectedIdentifiers:selectedId?new Set(groups.find(g=>g.id===selectedId).source_references.map(r=>r.identifier)):null})))));}
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(Demo));
</script></body></html>`}))
try {
await page.goto('http://127.0.0.1:5182/__thesis_test__')
await page.getByRole('button',{name:'Inscrição em cadastro de inadimplentes',exact:true}).waitFor()
assert.equal(await page.locator('.compact-theses > li').count(),4)
assert.equal(await page.locator('.compact-theses a').count(),0)
assert.equal(await page.locator('a[href^="javascript:"]').count(),0)
for (const title of await page.locator('.thesis-row-main').allTextContents()) assert.ok(title.length<=65)
assert.equal(await page.locator('.thesis-statement').first().isVisible(),false)
await page.locator('.thesis-full-text > summary').first().click()
assert.equal(await page.locator('.thesis-statement').first().isVisible(),true)
assert.ok((await page.locator('.thesis-statement').first().innerText()).includes('se demonstrados os requisitos.'))
await page.locator('.thesis-full-text > summary').first().click()
const button=page.getByRole('button',{name:'Nexo causal',exact:true})
await button.click();assert.equal(await button.getAttribute('aria-pressed'),'true')
assert.equal(await page.locator('.thesis-related-sources li').count(),1)
assert.match(await page.locator('.thesis-related-sources').innerText(),/FONTE-TESTE-1/)
await button.click();assert.equal(await button.getAttribute('aria-pressed'),'false')
assert.equal(await page.locator('.thesis-related-sources li').count(),5)
for(const width of [320,760,1440]) {
 await page.setViewportSize({width,height:1050})
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth), 'No horizontal overflow at '+width)
}
await page.screenshot({path:'tests/thesis-groups-preview.png',fullPage:true})
assert.deepEqual(errors,[])
console.log('PASS: long statements become short titles; summaries collapsed; expansion, source filtering, safe links, responsive 320/760/1440; no browser errors.')
} finally {await browser.close()}
