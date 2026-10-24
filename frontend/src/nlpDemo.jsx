import { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import NlpPanel from './NlpPanel'
import { authRequest } from './authApi'
import './index.css'

const context = JSON.stringify({ courts: ['STJ'], subject_codes: [10433], start: '2024-01-01', end: '2024-12-31', sources: ['stj_jurisprudence'] })
export default function Demo() {
  const [state, setState] = useState('loading')
  useEffect(() => {
    let active = true
    if (!['127.0.0.1', 'localhost'].includes(location.hostname) || location.port !== '5180') return
    authRequest('auth/login', 'POST', { login: 'fx115-demo@example.invalid', password: 'FX115-local-demo-only' })
      .then(() => { if (active) setState('ready') })
      .catch(error => { if (active) setState(error.message) })
    return () => { active = false }
  }, [])
  return <main className="dashboard"><header><span className="eyebrow">DatumLex · demonstração local isolada</span><h1>Veja o NLP em funcionamento</h1>
    <p><strong>FX115-DEMO — três documentos sintéticos. Revisão e liberação simuladas, sem validade jurídica.</strong></p>
    <p>O extrator por regras existente gerou as anotações. Este painel consulta a API e as evidências persistidas em um banco exclusivo da demonstração. Não há LLM nem estimativa de vitória.</p>
  </header>{state === 'ready' ? <NlpPanel contextKey={context} /> : <p role="status">{state === 'loading' ? 'Conectando à API da demonstração…' : state}</p>}</main>
}
createRoot(document.getElementById('root')).render(<Demo />)
