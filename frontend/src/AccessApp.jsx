import { useEffect, useState } from 'react'
import { ArrowRight, Check, Clock3, Eye, EyeOff, LogOut, Plus, Search, ShieldCheck, Users, ChartNoAxesCombined, Pencil, Trash2 } from 'lucide-react'
import App from './App.jsx'
import { authRequest } from './authApi'

const blankUser = { name: '', cpf: '', email: '', role: 'Padrão', status: 'Pendente', courts: [], must_change_password: true }
const cpfDigits = (value) => value.replace(/\D/g, '')
const cpfLabel = (value) => value.replace(/(\d{3})(\d{3})(\d{3})(\d{2})/, '$1.$2.$3-$4')
function Logo() { return <img className="access-logo" src="/assets/datumlex-logo-horizontal.jpg" alt="DatumLex" /> }
function Password({ label = 'Senha', minimum = 8, name = 'password', required = true }) {
  const [visible, setVisible] = useState(false)
  return <label className="access-field"><span>{label}</span><div className="password-control"><input name={name} type={visible ? 'text' : 'password'} required={required} minLength={minimum} autoComplete={minimum === 1 ? "current-password" : "new-password"} placeholder={minimum === 1 ? "Informe sua senha" : "No mínimo 8 caracteres"} /><button type="button" aria-label={visible ? 'Ocultar senha' : 'Mostrar senha'} onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={19} /> : <Eye size={19} />}</button></div></label>
}
function IdentityFields({ value, onChange }) {
  return <><label className="access-field"><span>Nome completo</span><input name="name" autoComplete="name" required value={value.name} onChange={(e) => onChange({ ...value, name: e.target.value })} placeholder="Informe o nome completo" /></label><label className="access-field"><span>CPF</span><input name="cpf" inputMode="numeric" autoComplete="off" required pattern="[0-9.\-]{11,14}" maxLength={14} value={value.cpf} onChange={(e) => onChange({ ...value, cpf: e.target.value })} placeholder="000.000.000-00" /></label><label className="access-field"><span>E-mail</span><input name="email" type="email" autoComplete="email" required value={value.email} onChange={(e) => onChange({ ...value, email: e.target.value })} placeholder="nome@exemplo.com" /></label></>
}
function Badge({ children }) { return <span className={`access-badge ${children === 'Pendente' ? 'pending' : children === 'Ativo' ? 'active' : ''}`}>{children === 'Pendente' ? <Clock3 size={13} /> : children === 'Ativo' ? <Check size={13} /> : null}{children}</span> }

export default function AccessApp() {
  const [users, setUsers] = useState([])
  const [courts, setCourts] = useState([])
  const [booting, setBooting] = useState(true)
  const [busy, setBusy] = useState(false)
  const [listLoading, setListLoading] = useState(false)
  const [session, setSession] = useState(null)
  const [screen, setScreen] = useState('login')
  const [registration, setRegistration] = useState({ ...blankUser })
  const [editor, setEditor] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [query, setQuery] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [pendingOnly, setPendingOnly] = useState(false)
  const [ascending, setAscending] = useState(true)
  const [selectedCourt, setSelectedCourt] = useState('TJDFT')
  const canManage = session && session.role !== 'Padrão'
  const canEdit = (user) => canManage && (session.role === 'Master' || user.role === 'Padrão')
  function navigate(next) { setScreen(next); setError(''); setNotice(''); setEditor(null); setDeleting(null) }
  function validate(user) {
    if (user.name.trim().split(/\s+/).length < 2) return 'Informe o nome completo.'
    if (cpfDigits(user.cpf).length !== 11) return 'Informe um CPF com 11 dígitos.'
    if (users.some((item) => item.id !== user.id && (item.email.toLowerCase() === user.email.trim().toLowerCase() || item.cpf === cpfDigits(user.cpf)))) return 'Este CPF ou e-mail já está cadastrado.'
    return ''
  }
  useEffect(() => {
    let active = true
    const expired = () => { setSession(null); setUsers([]); setScreen('login') }
    window.addEventListener('datumlex:session-ended', expired)
    async function restore() {
      try {
        await authRequest('auth/csrf')
        const data = await authRequest('auth/me')
        if (active) {
          setSession(data.user); setCourts(data.courts.map((c) => c.code)); setSelectedCourt(data.user.courts[0] || '')
          setScreen('consultas')
        }
      } catch (failure) { if (active && failure.status !== 401) setError(failure.message) }
      finally { if (active) setBooting(false) }
    }
    restore()
    return () => { active = false; window.removeEventListener('datumlex:session-ended', expired) }
  }, [])
  useEffect(() => {
    if (!canManage || screen !== 'usuarios' || session.must_change_password) return
    let active = true
    Promise.resolve().then(() => { if (active) setListLoading(true) })
    authRequest('users').then((data) => { if (active) setUsers(data.users) }).catch((failure) => { if (active) setError(failure.message) }).finally(() => { if (active) setListLoading(false) })
    return () => { active = false }
  }, [canManage, screen, session?.must_change_password])
  async function save(event) {
    event.preventDefault()
    if (!canEdit(editor) || busy) return
    const message = validate(editor)
    if (message) { setError(message); return }
    const payload = Object.fromEntries(['name', 'email', 'cpf', 'role', 'status', 'courts'].map((key) => [key, editor[key]]))
    if (!editor.id) payload.must_change_password = editor.must_change_password
    const form = new FormData(event.currentTarget)
    if (!editor.id || (session.role === 'Master' && (form.get('password') || form.get('confirmation')))) {
      if (form.get('password') !== form.get('confirmation')) { setError('As senhas não coincidem. Digite a mesma senha nos dois campos.'); return }
      payload.password = form.get('password')
      if (editor.id) payload.password_confirmation = form.get('confirmation')
    }
    setBusy(true); setError('')
    try {
      const { user } = await authRequest(editor.id ? `users/${editor.id}` : 'users', editor.id ? 'PATCH' : 'POST', payload)
      setUsers((items) => editor.id ? items.map((item) => item.id === user.id ? user : item) : [...items, user])
      if (user.id === session.id) { setSession(user); setSelectedCourt(user.courts[0] || '') }
      setEditor(null); setNotice('Cadastro salvo com sucesso.')
    } catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }
  async function signOut() {
    try { await authRequest('auth/logout', 'POST'); setSession(null); setUsers([]); navigate('login') }
    catch (failure) { setError(failure.message) }
  }
  async function removeUser() {
    if (busy) return
    setBusy(true); setError('')
    try { await authRequest(`users/${deleting.id}`, 'DELETE'); setUsers(users.filter((u) => u.id !== deleting.id)); setDeleting(null); setNotice('Usuário excluído.') }
    catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }
  async function submitAuth(event) {
    event.preventDefault()
    if (busy) return
    const form = new FormData(event.currentTarget)
    if (screen === 'register' && form.get('password') !== form.get('confirmation')) { setError('As senhas não coincidem. Digite a mesma senha nos dois campos.'); return }
    setBusy(true); setError('')
    try {
      if (screen === 'register') {
        await authRequest('auth/register', 'POST', { name: registration.name, email: registration.email, cpf: registration.cpf, password: form.get('password') })
        setRegistration({ ...blankUser }); navigate('pending')
      } else {
        await authRequest('auth/login', 'POST', { login: form.get('login'), password: form.get('password') })
        const data = await authRequest('auth/me')
        setSession(data.user); setCourts(data.courts.map((c) => c.code)); setSelectedCourt(data.user.courts[0] || '')
        navigate('consultas')
      }
    } catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }
  if (booting) return <main className="access-empty" role="status">Carregando sua sessão…</main>
  if (session && (session.must_change_password || screen === 'password')) return <main className="auth-layout"><section className="auth-card"><Logo /><div className="auth-heading"><h1>Alterar senha</h1><p>{session.must_change_password ? 'Defina sua senha pessoal para liberar o acesso.' : 'Escolha uma nova senha com pelo menos 8 caracteres.'}</p></div><form onSubmit={async (event) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    if (form.get('password') !== form.get('confirmation')) { setError('As senhas não coincidem.'); return }
    setBusy(true); setError('')
    try { const data = await authRequest('auth/password', 'POST', { current_password: form.get('current_password'), password: form.get('password') }); setSession(data.user); navigate('consultas') }
    catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }}><Password name="current_password" label="Senha atual" minimum={1} /><Password label="Nova senha" /><Password name="confirmation" label="Confirmar nova senha" />{error && <p className="access-error" role="alert">{error}</p>}<button className="access-primary" type="submit" disabled={busy}>Salvar nova senha</button></form><button className="text-button" onClick={signOut}>Sair</button></section></main>
  if (!session) return <div className="access-root"><div className="top-rule" /><main className="auth-layout"><section className="auth-card"><Logo />{screen === 'pending' ? <div className="pending-state"><div className="state-symbol"><Clock3 size={30} /></div><span className="eyebrow">Cadastro enviado</span><h1>Aguardando aprovação</h1><p>Seu cadastro recebeu o perfil Padrão. Um responsável deverá aprovar o acesso e definir os tribunais disponíveis.</p><div className="access-info">Seu cadastro foi recebido. Você poderá entrar assim que um responsável aprovar o acesso.</div><button className="access-primary" onClick={() => navigate('login')}>Voltar ao login <ArrowRight size={18} /></button></div> : <><div className="auth-heading"><span className="eyebrow">Inteligência jurídica</span><h1>{screen === 'register' ? 'Crie sua conta' : 'Bem-vindo ao DatumLex'}</h1><p>{screen === 'register' ? 'Preencha seus dados para solicitar acesso.' : 'Acesse sua conta para consultar os dados judiciais.'}</p></div><form onSubmit={submitAuth}>{screen === 'register' ? <IdentityFields value={registration} onChange={setRegistration} /> : <label className="access-field"><span>E-mail ou CPF</span><input name="login" required autoComplete="username" placeholder="Informe seu e-mail ou CPF" /><small>Suporte: utilize o usuário suport.</small></label>}<Password minimum={screen === 'register' ? 8 : 1} />{screen === 'register' && <Password name="confirmation" label="Confirmar senha" />}{screen === 'register' && <p className="field-help">Mínimo de 8 caracteres. Números e símbolos são opcionais.</p>}{error && <p className="access-error" role="alert">{error}</p>}<button className="access-primary" type="submit" disabled={busy}>{screen === 'register' ? 'Solicitar cadastro' : 'Entrar'}<ArrowRight size={18} /></button></form><p className="auth-switch">{screen === 'register' ? 'Já possui cadastro?' : 'Ainda não possui uma conta?'} <button className="text-button" onClick={() => navigate(screen === 'register' ? 'login' : 'register')}>{screen === 'register' ? 'Voltar ao login' : 'Criar conta'}</button></p><div className="auth-security"><ShieldCheck size={18} /><span>O acesso depende da aprovação do seu cadastro.</span></div></>}</section></main><footer className="access-footer">DatumLex · Inteligência para decisões fundamentadas</footer></div>

  const filtered = users.filter((user) => (!roleFilter || user.role === roleFilter) && (!pendingOnly || user.status === 'Pendente') && `${user.name} ${user.email} ${user.cpf} ${cpfLabel(user.cpf)}`.toLowerCase().includes(query.toLowerCase())).sort((a, b) => (ascending ? 1 : -1) * a.name.localeCompare(b.name, 'pt-BR'))
  return <div className="access-root"><div className="top-rule" /><header className="workspace-header"><Logo /><nav aria-label="Navegação principal"><button className={screen === 'consultas' ? 'selected' : ''} onClick={() => navigate('consultas')}><ChartNoAxesCombined size={18} />Menu</button>{canManage && <button className={screen === 'usuarios' ? 'selected' : ''} onClick={() => navigate('usuarios')}><Users size={18} />Usuários</button>}</nav><div className="session-details">{!session.support && <button className="text-button" onClick={() => navigate('password')}>Alterar senha</button>}<span>{session.name}<small>{session.support ? 'Master · Suporte' : session.role}</small></span><button title="Sair" aria-label="Sair da conta" onClick={signOut}><LogOut size={19} /></button></div></header>{error && !editor && <p className="access-error" role="alert">{error}</p>}
    {screen === 'consultas' ? <section className="consultation-wrap">{session.courts.length ? <App key={selectedCourt} court={selectedCourt} courts={session.courts} onCourtChange={setSelectedCourt} /> : <div className="access-empty"><ChartNoAxesCombined size={32} /><h2>Nenhum tribunal autorizado</h2><p>Solicite a liberação dos tribunais ao responsável pelo seu cadastro.</p></div>}</section> : canManage && <main className="users-main"><div className="users-heading"><div><span className="eyebrow">Administração de acesso</span><h1>Gerenciamento de usuários</h1><p>Organize os acessos e os tribunais disponíveis para sua equipe.</p></div><button className="access-primary" onClick={() => { setEditor({ ...blankUser }); setError(''); setNotice('') }}><Plus size={18} />Cadastrar usuário</button></div>
    <div className="access-stats"><article><span>Usuários cadastrados</span><strong>{users.length}</strong><small>Cadastros da equipe</small></article><article><span>Acessos ativos</span><strong>{users.filter((u) => u.status === 'Ativo').length}</strong><small>Usuários com cadastro aprovado</small></article><article><span>Aguardando aprovação</span><strong>{users.filter((u) => u.status === 'Pendente').length}</strong><small>Revise as permissões antes de aprovar</small></article></div>
    {session.role === 'Admin' && <div className="access-info"><ShieldCheck size={18} />Você pode editar e aprovar somente usuários Padrão.</div>}{notice && <p className="access-success" role="status">{notice}</p>}
    {listLoading && <p role="status">Carregando usuários…</p>}<button className="text-button" disabled={listLoading} onClick={async () => { setListLoading(true); setError(''); try { const data = await authRequest('users'); setUsers(data.users) } catch (failure) { setError(failure.message) } finally { setListLoading(false) } }}>Atualizar usuários</button>{editor ? <section className="editor-panel"><div className="section-heading"><div><span className="eyebrow">Dados e permissões</span><h2>{editor.id ? 'Editar usuário' : 'Cadastrar usuário'}</h2></div><button className="secondary-button" onClick={() => { setEditor(null); setError('') }}>Cancelar</button></div><form onSubmit={save}><div className="editor-grid"><IdentityFields value={editor} onChange={setEditor} />{!editor.id && <><Password /><Password name="confirmation" label="Confirmar senha" /><label className="password-policy"><input type="checkbox" checked={editor.must_change_password} onChange={(event) => setEditor({ ...editor, must_change_password: event.target.checked })} />Exigir alteração de senha no primeiro acesso</label></>}{editor.id && session.role === 'Master' && <><Password label="Nova senha" required={false} /><Password name="confirmation" label="Confirmar nova senha" required={false} /><p className="field-help">Para manter a senha atual, deixe os dois campos vazios. A nova senha deve ter pelo menos 8 caracteres. Ao redefini-la, o usuário deverá alterá-la no próximo acesso.</p></>}<label className="access-field"><span>Perfil de acesso</span><select value={editor.role} disabled={session.role !== 'Master' || editor.id === session.id} onChange={(e) => setEditor({ ...editor, role: e.target.value })}>{['Padrão', 'Admin', 'Master'].map((role) => <option key={role}>{role}</option>)}</select>{editor.id === session.id && <small>Você não pode alterar seu próprio perfil.</small>}</label><label className="access-field"><span>Status do cadastro</span><select value={editor.status} onChange={(e) => setEditor({ ...editor, status: e.target.value })}><option>Pendente</option><option>Ativo</option><option>Inativo</option></select></label></div><fieldset className="court-picker"><legend>Tribunais permitidos</legend><p>Selecione os tribunais que este usuário poderá consultar.</p><div className="court-actions"><button type="button" className="text-button" onClick={() => setEditor({ ...editor, courts: [...courts] })}>Selecionar todos</button><button type="button" className="text-button" onClick={() => setEditor({ ...editor, courts: [] })}>Limpar seleção</button><span>{editor.courts.length} de {courts.length} selecionados</span></div><div className="court-options">{courts.map((court) => <label key={court}><input type="checkbox" checked={editor.courts.includes(court)} onChange={(e) => setEditor({ ...editor, courts: e.target.checked ? [...editor.courts, court] : editor.courts.filter((item) => item !== court) })} />{court}</label>)}</div></fieldset>{editor.status === 'Ativo' && !editor.courts.length && <p className="access-info">Sem tribunais selecionados, este usuário não poderá visualizar consultas.</p>}{error && <p className="access-error" role="alert">{error}</p>}<div className="editor-actions"><button type="button" className="secondary-button" onClick={() => { setEditor(null); setError('') }}>Cancelar</button><button className="access-primary" type="submit" disabled={busy}><Check size={18} />Salvar alterações</button></div></form></section> : <section className="user-table-panel" aria-label="Usuários cadastrados"><div className="user-filters"><label className="access-field search-field"><span>Buscar usuário</span><div><Search size={18} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Nome, CPF ou e-mail" /></div></label><label className="access-field"><span>Perfil de acesso</span><select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}><option value="">Todos os perfis</option>{['Master', 'Admin', 'Padrão'].map((role) => <option key={role}>{role}</option>)}</select></label><label className="pending-filter"><input type="checkbox" checked={pendingOnly} onChange={(e) => setPendingOnly(e.target.checked)} />Somente pendentes</label></div><div className="table-scroll"><table className="users-table"><caption>{filtered.length} usuário(s) encontrado(s)</caption><thead><tr><th scope="col"><button onClick={() => setAscending(!ascending)}>Usuário {ascending ? '↑' : '↓'}</button></th><th scope="col">Perfil</th><th scope="col">Status</th><th scope="col">Tribunais</th><th scope="col">Ações</th></tr></thead><tbody>{filtered.map((user) => <tr key={user.id}><td><strong>{user.name}</strong><span>{user.email}</span><small>{cpfLabel(user.cpf)}</small></td><td><Badge>{user.role}</Badge></td><td><Badge>{user.status}</Badge></td><td><span>{user.courts.length === courts.length ? 'Todos os tribunais' : user.courts.join(', ') || 'Nenhum tribunal'}</span></td><td><div className="row-actions">{canEdit(user) ? <button aria-label={`${user.status === 'Pendente' ? 'Revisar e aprovar' : 'Editar'} ${user.name}`} onClick={() => { setEditor({ ...user, courts: [...user.courts] }); setError(''); setNotice('') }}><Pencil size={16} />{user.status === 'Pendente' ? 'Revisar e aprovar' : 'Editar'}</button> : <span className="read-only">Somente leitura</span>}{session.role === 'Master' && user.id !== session.id && <button className="delete-button" aria-label={`Excluir ${user.name}`} onClick={() => setDeleting(user)}><Trash2 size={16} /></button>}</div></td></tr>)}</tbody></table></div>{!listLoading && !error && !filtered.length && <div className="access-empty"><Search size={28} /><h2>Nenhum usuário encontrado</h2><p>Revise os termos da busca ou limpe os filtros.</p><button className="secondary-button" onClick={() => { setQuery(''); setRoleFilter(''); setPendingOnly(false) }}>Limpar filtros</button></div>}</section>}
    {deleting && <section className="delete-confirm" role="alert"><p>Excluir o cadastro de <strong>{deleting.name}</strong>?</p><div><button className="secondary-button" onClick={() => setDeleting(null)}>Cancelar</button><button className="danger-button" disabled={busy} onClick={removeUser}>Confirmar exclusão</button></div></section>}
    <footer className="access-footer">DatumLex · Gestão de acesso</footer></main>}
  </div>
}
