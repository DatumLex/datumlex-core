import { useEffect, useState } from 'react'
import { authRequest } from './authApi'
import './automation.css'

const states = { running: 'Em execução', completed: 'Concluída', partial: 'Concluída; há trimestres abaixo da meta',
  partial_failure: 'Concluída com falhas nas fontes', failed: 'Falhou', interrupted: 'Interrompida', blocked: 'Bloqueada por configuração ou acesso' }
const date = value => value ? new Date(value).toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo' }) : 'Não programada'

function SubjectCodes({ codes, disabled, onChange }) {
  const [text, setText] = useState(codes.join(', '))
  return <label>Códigos de assuntos CNJ<input value={text} pattern="[0-9, ]*" disabled={disabled} onChange={event => {
    setText(event.target.value)
    onChange(event.target.value.split(',').map(value => value.trim()).filter(Boolean).map(Number))
  }} /></label>
}

export default function AutomationPanel({ session }) {
  const [remote, setRemote] = useState(null)
  const [draft, setDraft] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let active = true
    authRequest('admin/automation').then(data => {
      if (!active) return
      setRemote(data)
      setDraft(current => current || data.config)
      setError('')
    }).catch(failure => { if (active) setError(failure.message) })
    return () => { active = false }
  }, [revision])

  function toggle(name, value, selected) {
    setDraft(current => ({ ...current, [name]: selected ? [...new Set([...current[name], value])] : current[name].filter(item => item !== value) }))
  }
  async function submit(event) {
    event.preventDefault()
    setBusy(true); setError(''); setNotice('')
    try {
      const data = await authRequest('admin/automation', 'PUT', draft)
      setRemote(data); setDraft(data.config)
      setNotice('Configuração salva no banco do servidor. Nenhuma coleta foi iniciada ao salvar.')
    } catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }
  async function act(action) {
    setBusy(true); setError(''); setNotice('')
    try {
      const data = await authRequest('admin/automation/actions', 'POST', { action })
      setRemote(data)
      setNotice(action === 'enable' ? 'Agendamento ativado no servidor.' : action === 'pause' ? 'Próximas coletas pausadas. Uma rodada em andamento pode terminar.' : 'Coleta colocada na fila. Ela começará na próxima verificação do executor.')
    } catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }
  const dirty = draft && remote && JSON.stringify(draft) !== JSON.stringify(remote.config)
  const last = remote?.last_run
  const missingKey = draft?.sources.includes('datajud') && !remote?.datajud_key_configured
  return <main className="users-main automation-panel">
    <div className="users-heading"><div><span className="eyebrow">Administração</span><h1>Extração automática</h1><p>Escolha o que coletar e salve a configuração no servidor.</p></div></div>
    {error && <div className="access-error" role="alert">{error}<button className="secondary-button" onClick={() => setRevision(value => value + 1)}>Tentar novamente</button></div>}
    {notice && <p className="access-info" role="status">{notice}</p>}
    {!remote && !error && <p role="status">Carregando configuração…</p>}
    {remote && draft && <>
      <section className="automation-status" aria-label="Situação da automação">
        <strong>{remote.enabled ? 'Agendamento ativo' : 'Agendamento pausado'}</strong>
        <p>Configuração salva no banco do servidor. Não depende deste navegador ou do computador do cliente.</p>
        <p>Executor: {remote.executor_ready ? 'conectado' : 'ainda não conectado; você já pode salvar suas escolhas'}.</p>
        {remote.enabled && !remote.executor_ready && <p role="status">O horário continua salvo, mas o executor está indisponível. A coleta aguarda sua reconexão.</p>}
        <p>Próxima coleta: {date(remote.next_run_at)} · horário de Brasília.</p>
        <p>Última rodada: {last ? states[last.status] || last.status : 'nenhuma execução registrada'}{last?.finished_at ? ` · ${date(last.finished_at)}` : ''}.</p>
        {remote.requested && <p role="status">Uma coleta está aguardando o executor.</p>}
        <button className="secondary-button" type="button" disabled={busy} onClick={() => setRevision(value => value + 1)}>Atualizar status</button>
      </section>
      <form className="automation-form" onSubmit={submit}>
        <fieldset disabled={busy}><legend>1. O que você quer coletar?</legend><div className="automation-options">{remote.sources.map(source => <label key={source.id}>
          <input type="checkbox" disabled={!source.available} checked={draft.sources.includes(source.id)} onChange={event => toggle('sources', source.id, event.target.checked)} />
          <span>{source.label}<small>{source.provider}{!source.available ? ' · integração com esta automação pendente' : ''}</small></span>
        </label>)}</div><p>O DataJud fornece dados processuais, sem garantia de texto completo. Teses e precedentes vêm do Pangea. Documentos coletados não são aprovados automaticamente pelo NLP.</p>
        {missingKey && <p role="status">A chave DataJud ainda precisa ser configurada pelo responsável no servidor. Você pode salvar a configuração enquanto isso.</p>}</fieldset>
        <fieldset disabled={busy}><legend>2. Tribunais e temas</legend><div className="automation-actions"><button type="button" className="text-button" onClick={() => setDraft({ ...draft, courts: [...session.courts] })}>Selecionar todos os tribunais</button><span>{draft.courts.length} selecionados</span></div><div className="automation-options">{session.courts.map(code => <label key={code}><input type="checkbox" checked={draft.courts.includes(code)} onChange={event => toggle('courts', code, event.target.checked)} />{code}</label>)}</div>
        {draft.sources.includes('pangea') && <><p>Temas para buscar no Pangea:</p><div className="automation-options">{remote.topics.map(item => <label key={item.id}><input type="checkbox" checked={draft.topics.includes(item.id)} onChange={event => toggle('topics', item.id, event.target.checked)} />{item.label}</label>)}</div></>}</fieldset>
        <fieldset disabled={busy}><legend>3. Período e horário</legend><div className="automation-fields">
          <label>Ano inicial<input type="number" min="2016" max={new Date().getFullYear()} value={draft.start_year} onChange={event => setDraft({ ...draft, start_year: Number(event.target.value) })} required /></label>
          <label>Ano final<input type="number" min={draft.start_year} max={new Date().getFullYear()} value={draft.end_year} onChange={event => setDraft({ ...draft, end_year: Number(event.target.value) })} required /></label>
          <label>Horário diário, em Brasília<input type="time" value={draft.daily_at} onChange={event => setDraft({ ...draft, daily_at: event.target.value })} required /></label>
        </div><p>O período vale para os processos DataJud; o ano atual vai até a data da coleta. Precedentes não recebem datas inventadas. O executor verifica a fila periodicamente, então o início pode ocorrer após o horário escolhido.</p>
        </fieldset>
        <details className="automation-advanced"><summary>Ajustes avançados</summary><div className="automation-fields">
          <label>Meta total por trimestre<input type="number" min="1" max="10000" value={draft.quarter_target} onChange={event => setDraft({ ...draft, quarter_target: Number(event.target.value) })} required disabled={busy} /></label>
          <label>Páginas DataJud por rodada<input type="number" min="1" max="40" value={draft.max_pages} onChange={event => setDraft({ ...draft, max_pages: Number(event.target.value) })} required disabled={busy} /></label>
          <SubjectCodes codes={draft.subject_codes} disabled={busy} onChange={codes => setDraft({ ...draft, subject_codes: codes })} />
        </div><p>A meta de {draft.quarter_target} registros é somada entre todos os tribunais selecionados, não por tribunal. Cada página DataJud tem até 100 registros; Pangea consulta até uma página por tema. A disponibilidade das fontes pode impedir o preenchimento da meta.</p></details>
        <section className="automation-summary" aria-label="Resumo da configuração"><strong>Seu agendamento</strong><p>{draft.courts.length} tribunais · {draft.start_year} a {draft.end_year} · todos os dias às {draft.daily_at}, em Brasília.</p></section>
        <div className="automation-actions"><button className="access-primary" type="submit" disabled={busy}>Salvar configuração</button><button className="secondary-button" type="button" disabled={busy || dirty || !remote.executor_ready || missingKey || remote.enabled} onClick={() => act('enable')}>Ativar agendamento</button><button className="secondary-button" type="button" disabled={busy || (!remote.enabled && !remote.requested)} onClick={() => act('pause')}>Pausar</button><button className="secondary-button" type="button" disabled={busy || dirty || !remote.executor_ready || missingKey || remote.requested || last?.status === 'running'} onClick={() => act('run_once')}>Solicitar uma coleta</button></div>
        {dirty && <p role="status">Salve as alterações antes de ativar ou solicitar uma coleta.</p>}
      </form>
    </>}
  </main>
}
