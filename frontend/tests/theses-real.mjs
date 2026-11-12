// Read-only response capture from local database; no database writes.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { chromium } from '@playwright/test'
const dir=process.env.REAL_QA_DIR
if(!dir) throw new Error('Set REAL_QA_DIR to a directory with captured real-alignment.json and real-dashboard.json')
const alignment=JSON.parse(await readFile(`${dir}/real-alignment.json`,'utf8'))
const dashboard=JSON.parse(await readFile(`${dir}/real-dashboard.json`,'utf8'))
const browser=await chromium.launch({channel:'msedge',headless:true})
const page=await browser.newPage({viewport:{width:1440,height:1050}})
const errors=[];page.on('pageerror',error=>errors.push(error.message))
await page.route('**/api/**',route=>{
 const resource=new URL(route.request().url()).pathname.split('/')[2]
 return route.fulfill({json:resource==='alignment'?alignment:dashboard[resource] || {items:[],results:[],topics:[],total:0}})
})
await page.route('**/__real_theses__', route=>route.fulfill({contentType:'text/html',body:`<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="root"></div><script type="module">
import React from '/node_modules/.vite/deps/react.js';import ReactDOM from '/node_modules/.vite/deps/react-dom_client.js';
import RefreshRuntime from '/@react-refresh';RefreshRuntime.injectIntoGlobalHook(window);window.$RefreshReg$=()=>{};window.$RefreshSig$=()=>type=>type;window.__vite_plugin_react_preamble_installed__=true;
const {default:App}=await import('/src/App.jsx');import '/src/index.css';ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App,{court:'TJDFT',courts:['TJDFT']}));
</script></body></html>`}))
try{
 await page.goto('http://127.0.0.1:5182/__real_theses__')
 await page.getByRole('tab',{name:'Precedentes e teses',exact:true}).click()
 await page.getByRole('heading',{name:'Teses disponíveis',exact:true}).waitFor()
 assert.equal(await page.locator('#panel-precedents .nlp-controls').count(),0)
 assert.equal(await page.locator('.compact-theses > li').count(),25)
 assert.ok((await page.locator('.thesis-card').innerText()).includes(`de ${alignment.thesis_groups.length} teses`))
 await page.getByRole('button',{name:'Próximas teses',exact:true}).click()
 assert.ok((await page.locator('.thesis-card').innerText()).includes('página 2'))
 const group=alignment.thesis_groups.find(g=>g.related_decisions?.length && g.source_references?.length)
 const ref=group.source_references[0].identifier
 await page.getByRole('searchbox',{name:'Buscar tese'}).fill(ref)
 const row=page.locator('.compact-theses > li').filter({has:page.getByRole('button',{name:group.label,exact:true})}).first()
 await row.getByRole('button').first().click()
 await page.locator('.source-citation-item').first().waitFor()
 const expected=new Set(group.source_references.map(r=>r.identifier))
 const links=await page.locator('.thesis-related-sources li strong').allTextContents()
 assert.ok(links.length>0)
 for(const link of links) assert.ok([...expected].some(id=>link.includes(id)))
 assert.equal(await row.locator('.thesis-statement').first().isVisible(),false)
 await row.getByText('Resumo da tese',{exact:true}).click()
 assert.equal(await row.locator('.thesis-statement').first().isVisible(),true)
 await row.getByText('Resumo da tese',{exact:true}).click()
 await page.getByRole('searchbox',{name:'Buscar tese'}).fill('')
 for(const width of [320,760,1440]){
   await page.setViewportSize({width,height:1050})
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Reflow '+width)
 }
 await page.locator('#panel-precedents').screenshot({path:`${dir}/teses-reais.png`})
 assert.deepEqual(errors,[])
 console.log(`PASS: actual App; ${alignment.thesis_groups.length} real theses; pagination, search, click-to-related-decisions, source isolation, collapsed summaries, responsive 320/760/1440.`)
}finally{await browser.close()}
