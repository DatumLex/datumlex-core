import { useState } from 'react'
import { legalChatRequest, legalDraftExportUrl, reportUrl, safeOfficialUrl } from './nlpApi'
import './legalChat.css'

export default function LegalChat({ snapshot }) {
  const [question, setQuestion] = useState('Quais fundamentos aparecem nas fontes selecionadas e quais limitações devo considerar?')
  const [consent, setConsent] = useState(false)
  const [turns, setTurns] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [conclusions, setConclusions] = useState('')
  const [reviewed, setReviewed] = useState(false)
  const draft = turns.at(-1)
  async function generate(event) {
    event?.preventDefault()
    setBusy(true); setError('')
    try {
      const result = await legalChatRequest(`analysis-snapshots/${snapshot.snapshot_id}/chat/`, {
        question, consent, ...(draft ? { parent_id: draft.draft_id } : {}),
      })
      if (result.snapshot_id !== snapshot.snapshot_id) throw new Error('Contexto da resposta não corresponde à consulta.')
      setTurns(current => [...current, result]); setConclusions(''); setReviewed(false)
    } catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }
  async function approve() {
    setBusy(true); setError('')
    try {
      const result = await legalChatRequest(`legal-drafts/${draft.draft_id}/`, {
        expected_sha256: draft.sha256, conclusions, confirmed: reviewed,
      })
      setTurns(current => [...current.slice(0, -1), result])
    } catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }
  return <section className="legal-chat" aria-labelledby="legal-chat-title" aria-busy={busy}>
    <h3 id="legal-chat-title">Chat de análise com fontes · Gemini</h3>
    <p>Assistente de pesquisa. Não substitui a avaliação profissional nem prevê resultados. Cada pergunta usa somente os trechos do contexto salvo; respostas anteriores não são usadas como evidência.</p>
    <p>Snapshot: <code>{snapshot.snapshot_id}</code> · {snapshot.data_mode !== 'live' ? 'Demonstração: fontes sintéticas' : 'Base local parcial'}</p>
    <form onSubmit={generate}>
      <label htmlFor="chat-question">Pergunta sobre a pesquisa</label>
      <textarea id="chat-question" rows={3} value={question} maxLength={2000} required minLength={3} onChange={event => setQuestion(event.target.value)} />
      <label className="chat-check"><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} />Autorizo o envio desta pergunta, dos filtros e dos trechos selecionados ao Google Gemini. Não incluirei dados sigilosos. A modalidade gratuita pode usar o conteúdo para melhorar os produtos Google.</label>
      <button className="apply-button" disabled={busy || !consent} type="submit">{busy ? 'Processando…' : 'Enviar pergunta'}</button>
      {draft && <button className="secondary-button" type="button" disabled={busy || !consent} onClick={() => generate()}>Regenerar / criar nova versão</button>}
    </form>
    {error && <p role="alert">{error}</p>}
    <div role="log" aria-label="Histórico de análises" aria-live="polite">
      {turns.map((turn, index) => <article key={turn.draft_id} className="chat-turn">
        <h4>Versão {index + 1} · {turn.status === 'approved' ? 'Aprovada pelo usuário' : 'Rascunho — revisão obrigatória'}</h4>
        <p><strong>Pergunta:</strong> {turn.question}</p>
        <h5>Fatos observados nos trechos</h5>
        {turn.facts.map((fact, i) => <blockquote key={i}>{fact.quote}<footer>Fonte: {fact.evidence_id}</footer></blockquote>)}
        <h5>Interpretação gerada — conferir suporte jurídico</h5>
        {turn.interpretations.map((item, i) => <p key={i}>{item.text}<br /><small>Fontes: {item.evidence_ids.join(', ')}</small></p>)}
        <h5>Incertezas e limites</h5>
        <ul>{[...turn.uncertainties, ...turn.warnings].map((text, i) => <li key={i}>{text}</li>)}</ul>
        <details><summary>Inspecionar fontes e versões ({turn.sources.length})</summary>
          {turn.sources.map(source => <div key={source.id}><p><strong>{source.document_id}</strong><br />Evidência: {source.id} · Revisão {source.revision}<br />Versão do texto: {source.text_version_id}<br />SHA-256: {source.text_sha256}</p>
            {source.passages.map((text, i) => <blockquote key={i}>{text}</blockquote>)}
            {safeOfficialUrl(source.official_url) && <a href={safeOfficialUrl(source.official_url)} target="_blank" rel="noreferrer">Consultar fonte oficial</a>}
          </div>)}
        </details>
        <details><summary>Metadados da geração</summary><p>Modelo: {turn.model} · {turn.latency_ms} ms<br />Tokens: {turn.usage.totalTokenCount ?? 'Não informado'}<br />{turn.cost_note}<br />Trechos selecionados: {turn.retrieval.selected} de {turn.retrieval.total}<br />Contrato: {turn.contract_version} · Prompt: {turn.prompt_version}<br />SHA-256 do contexto: {turn.snapshot_sha256}</p></details>
        {turn.status === 'approved' && <><h5>Conclusões de autoria do usuário</h5><p className="chat-user-text">{turn.user_conclusions || 'Nenhuma conclusão adicional.'}</p><a href={legalDraftExportUrl(turn.draft_id)}>Baixar análise aprovada (JSON UTF-8)</a><p>Aprovada em {new Date(turn.approved_at).toLocaleString('pt-BR')}.</p></>}
      </article>)}
    </div>
    {draft && draft.status === 'draft' && <div className="chat-review">
      <label htmlFor="chat-conclusions">Suas conclusões e ajustes (autoria do usuário)</label>
      <textarea id="chat-conclusions" rows={5} maxLength={10000} value={conclusions} onChange={event => { setConclusions(event.target.value); setReviewed(false) }} />
      <p>O texto gerado é preservado para rastreabilidade. Registre correções acima ou gere outra versão. Alterações exigem nova confirmação.</p>
      <label className="chat-check"><input type="checkbox" checked={reviewed} onChange={event => setReviewed(event.target.checked)} />Revisei os trechos, as interpretações e possíveis contradições. Aprovo esta versão para exportação.</label>
      <button type="button" className="apply-button" disabled={busy || !reviewed} onClick={approve}>Aprovar versão revisada</button>
    </div>}
    <p><a href={reportUrl(snapshot.snapshot_id)} target="_blank" rel="noreferrer">Abrir relatório de evidências deste contexto</a> — esse relatório contém as evidências, sem incorporar o rascunho do chat.</p>
  </section>
}
