import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'

import { authRequest } from '../../src/authApi.js'

test('authRequest inicializa CSRF, envia cadastro público e atualiza o token rotacionado', async () => {
  const calls = []
  const originalFetch = globalThis.fetch
  const originalWindow = globalThis.window
  globalThis.window = { dispatchEvent() {} }
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, method: options.method, headers: options.headers, body: options.body, credentials: options.credentials })
    if (url.endsWith('/auth/csrf/')) {
      return { ok: true, status: 200, json: async () => ({ csrfToken: 'csrf-initial' }) }
    }
    if (url.endsWith('/auth/register/')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          user: { id: 42, role: 'Padrão', status: 'Ativo', courts: ['TJDFT'] },
          csrfToken: 'csrf-rotated',
          message: 'Cadastro concluído.',
        }),
      }
    }
    if (url.endsWith('/auth/logout/')) {
      return { ok: true, status: 200, json: async () => ({ csrfToken: 'csrf-after-logout' }) }
    }
    throw new Error(`Unexpected URL: ${url}`)
  }

  try {
    const registered = await authRequest('auth/register', 'POST', {
      name: 'Pessoa Teste',
      email: 'teste@example.com',
      cpf: '11144477735',
      password: 'password123',
    })
    assert.equal(registered.user.role, 'Padrão')
    assert.equal(registered.user.status, 'Ativo')
    await authRequest('auth/logout', 'POST')

    assert.equal(calls.length, 3)
    assert.equal(calls[0].url, '/api/auth/csrf/')
    assert.equal(calls[1].url, '/api/auth/register/')
    assert.equal(calls[1].headers['X-CSRFToken'], 'csrf-initial')
    assert.equal(calls[1].credentials, 'include')
    assert.equal(calls[2].url, '/api/auth/logout/')
    assert.equal(calls[2].headers['X-CSRFToken'], 'csrf-rotated')
  } finally {
    globalThis.fetch = originalFetch
    globalThis.window = originalWindow
  }
})

test('AccessApp autentica direto no cadastro e não exige aprovação manual local', async () => {
  const source = await readFile(new URL('../../src/AccessApp.jsx', import.meta.url), 'utf8')
  assert.match(source, /authRequest\('auth\/register', 'POST'/)
  assert.doesNotMatch(source, /navigate\('pending'\)/)
  assert.doesNotMatch(source, /pending-state/)
  assert.doesNotMatch(source, /Solicitar cadastro/)
  assert.doesNotMatch(source, /O acesso depende da aprovação do seu cadastro/)
  assert.match(source, /Cadastro concluído\. Sua conta já está ativa\./)
  assert.match(source, /O cadastro está fechado nesta demonstração\./)
  assert.match(source, /Gerenciamento de usuários/)
})
