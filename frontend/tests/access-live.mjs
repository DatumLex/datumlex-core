import assert from 'node:assert/strict'
import { randomInt, randomUUID } from 'node:crypto'
import { pathToFileURL } from 'node:url'

const { chromium } = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href)
const origin = process.env.FRONTEND_URL || 'http://127.0.0.1:5174'
const secret = process.env.DATUMLEX_SUPPORT_PASSWORD
assert.ok(secret, 'Support deployment credential required through environment')
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const errors = []
page.on('pageerror', (error) => errors.push(error.message))
const ids = []
const marker = randomUUID().slice(0, 8)
const password = randomUUID()
const email = `integration-${marker}@example.com`
const pendingEmail = `pending-${marker}@example.com`
function cpf() {
  const values = Array.from({ length: 9 }, () => randomInt(10))
  for (const length of [9, 10]) values.push((values.reduce((sum, n, i) => sum + n * (length + 1 - i), 0) * 10 % 11) % 10)
  return values.join('')
}
async function api(path, method = 'GET', data) {
  const csrf = await context.request.get(`${origin}/api/auth/csrf/`)
  const { csrfToken } = await csrf.json()
  return context.request.fetch(`${origin}/api/${path}/`, { method, data, headers: { 'X-CSRFToken': csrfToken } })
}
async function login(identifier, pass) {
  await page.getByLabel('E-mail ou CPF').fill(identifier)
  await page.getByLabel('Senha', { exact: true }).fill(pass)
  await page.getByRole('button', { name: 'Entrar', exact: true }).click()
}
async function logout() { await page.getByRole('button', { name: 'Sair da conta' }).click(); await page.getByRole('heading', { name: 'Bem-vindo ao DatumLex' }).waitFor() }
try {
  await page.goto(origin)
  await page.getByRole('heading', { name: 'Bem-vindo ao DatumLex' }).waitFor()
  assert.equal(await page.getByText('Explore a interface').count(), 0)
  await login('suport', secret)
  await page.getByRole('button', { name: 'Menu', exact: true }).waitFor()
  await page.getByRole('button', { name: 'Usuários', exact: true }).click()
  await page.getByRole('heading', { name: 'Gerenciamento de usuários' }).waitFor()
  assert.equal(await page.getByRole('button', { name: 'Alterar senha', exact: true }).count(), 0)
  await page.getByRole('button', { name: 'Cadastrar usuário', exact: true }).click()
  assert.equal(await page.getByLabel('Exigir alteração de senha no primeiro acesso').isChecked(), true)
  await page.getByLabel('Nome completo').fill(`Integração Admin ${marker}`)
  await page.getByLabel('CPF', { exact: true }).fill(cpf())
  await page.getByLabel('E-mail', { exact: true }).fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByLabel('Confirmar senha', { exact: true }).fill(password)
  await page.getByLabel('Perfil de acesso').selectOption('Admin')
  await page.getByLabel('Status do cadastro').selectOption('Ativo')
  await page.getByLabel('TJDFT', { exact: true }).check()
  await page.getByRole('button', { name: 'Salvar alterações' }).click()
  await page.getByRole('status').filter({ hasText: 'Cadastro salvo' }).waitFor()
  let users = (await (await api('users')).json()).users
  ids.push(users.find((u) => u.email === email).id)
  assert.equal(users.some((u) => u.support), false)
  await logout()
  await login(email, password)
  await page.getByRole('heading', { name: 'Alterar senha', exact: true }).waitFor()
  await page.getByLabel('Senha atual', { exact: true }).fill(password)
  await page.getByLabel('Nova senha', { exact: true }).fill(`${password}new`)
  await page.getByLabel('Confirmar nova senha', { exact: true }).fill(`${password}new`)
  await page.getByRole('button', { name: 'Salvar nova senha' }).click()
  await page.getByRole('button', { name: 'Menu', exact: true }).waitFor()
  await page.getByRole('button', { name: 'Usuários', exact: true }).click()
  await page.getByRole('heading', { name: 'Gerenciamento de usuários' }).waitFor()
  assert.equal(await page.getByRole('button', { name: /^Excluir/ }).count(), 0)
  await logout()
  await page.getByRole('button', { name: 'Criar conta', exact: true }).click()
  await page.getByLabel('Nome completo').fill(`Integração Padrão ${marker}`)
  await page.getByLabel('CPF', { exact: true }).fill(cpf())
  await page.getByLabel('E-mail', { exact: true }).fill(pendingEmail)
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByLabel('Confirmar senha', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Solicitar cadastro' }).click()
  await page.getByRole('heading', { name: 'Aguardando aprovação' }).waitFor()
  await page.getByRole('button', { name: 'Voltar ao login' }).click()
  await login(pendingEmail, password)
  await page.getByRole('alert').filter({ hasText: 'pendente' }).waitFor()
  await login(email, `${password}new`)
  await page.getByRole('button', { name: 'Menu', exact: true }).waitFor()
  await page.getByRole('button', { name: 'Usuários', exact: true }).click()
  await page.getByRole('heading', { name: 'Gerenciamento de usuários' }).waitFor()
  users = (await (await api('users')).json()).users
  ids.push(users.find((u) => u.email === pendingEmail).id)
  await page.getByRole('button', { name: `Revisar e aprovar Integração Padrão ${marker}` }).click()
  assert.equal(await page.getByLabel('Perfil de acesso').isDisabled(), true)
  await page.getByLabel('Status do cadastro').selectOption('Ativo')
  await page.getByLabel('TJDFT', { exact: true }).check()
  await page.getByRole('button', { name: 'Salvar alterações' }).click()
  await page.getByRole('status').filter({ hasText: 'Cadastro salvo' }).waitFor()
  await logout()
  await login(pendingEmail, password)
  await page.getByRole('button', { name: 'Menu', exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: 'Usuários', exact: true }).count(), 0)
  assert.equal((await api('users')).status(), 403)
  await page.reload()
  await page.getByRole('button', { name: 'Menu', exact: true }).waitFor()
  assert.equal(await page.getByLabel('Tribunal', { exact: true }).inputValue(), 'TJDFT')
  await page.setViewportSize({ width: 320, height: 850 })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true)
  assert.deepEqual(errors, [])
  console.log('PASS: live PostgreSQL login, support hidden and fixed password, create Admin, mandatory password change, register/pending/approve, Standard access, session persistence, 320px layout.')
} finally {
  // Remove only test accounts created by this run; preserve their audit trail.
  await api('auth/login', 'POST', { login: 'suport', password: secret })
  const response = await api('users')
  if (response.ok()) {
    const users = (await response.json()).users
    for (const user of users.filter((u) => [email, pendingEmail].includes(u.email))) {
      const result = await api(`users/${user.id}`, 'DELETE')
      assert.equal(result.status(), 200, 'Test account cleanup failed')
    }
  }
  await api('auth/logout', 'POST')
  await browser.close()
}
