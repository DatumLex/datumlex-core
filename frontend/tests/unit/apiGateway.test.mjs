import assert from 'node:assert/strict'
import { test } from 'node:test'
import handler from '../../api/[...path].js'

function response() {
  return {
    statusCode: 0,
    headers: new Map(),
    setHeader(name, value) { this.headers.set(name, value) },
    status(code) { this.statusCode = code; return this },
    send(body) { this.body = body },
    json(body) { this.body = body },
    end() {},
  }
}

test('forwards authentication and cookies through the configured origin', async (t) => {
  const original = process.env.DATUMLEX_RAILWAY_ORIGIN
  process.env.DATUMLEX_RAILWAY_ORIGIN = 'https://api.example.test'
  t.after(() => {
    if (original === undefined) delete process.env.DATUMLEX_RAILWAY_ORIGIN
    else process.env.DATUMLEX_RAILWAY_ORIGIN = original
  })
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url.href, 'https://api.example.test/api/auth/login/?demo=1')
    assert.equal(options.method, 'POST')
    assert.equal(options.redirect, 'manual')
    assert.equal(options.headers.get('origin'), 'https://datumlex-core.vercel.app')
    assert.equal(options.headers.get('cookie'), 'csrftoken=existing')
    assert.equal(options.headers.get('x-csrftoken'), 'enabled')
    assert.deepEqual(JSON.parse(options.body), { login: 'fixture' })
    const headers = new Headers({ 'Content-Type': 'application/json' })
    headers.append('Set-Cookie', 'sessionid=fixture; Secure; HttpOnly; Path=/')
    headers.append('Set-Cookie', 'csrftoken=rotated; Secure; Path=/')
    return new Response('{"ok":true}', { headers })
  })
  const res = response()
  await handler({
    method: 'POST', url: '/api/auth/login/?demo=1', body: { login: 'fixture' },
    headers: {
      'content-type': 'application/json', cookie: 'csrftoken=existing',
      origin: 'https://datumlex-core.vercel.app', 'x-csrftoken': 'enabled',
    },
  }, res)
  assert.equal(res.statusCode, 200)
  assert.equal(res.headers.get('Cache-Control'), 'private, no-store')
  assert.equal(res.headers.get('Set-Cookie').length, 2)
  assert.deepEqual(JSON.parse(res.body), { ok: true })
})

test('preserves binary downloads and fails cleanly on upstream outages', async (t) => {
  const original = process.env.DATUMLEX_RAILWAY_ORIGIN
  process.env.DATUMLEX_RAILWAY_ORIGIN = 'https://api.example.test'
  t.after(() => {
    if (original === undefined) delete process.env.DATUMLEX_RAILWAY_ORIGIN
    else process.env.DATUMLEX_RAILWAY_ORIGIN = original
  })
  const bytes = Buffer.from([0, 255, 10])
  t.mock.method(globalThis, 'fetch', async (url) => {
    if (url.pathname.endsWith('health/')) throw new Error('network down')
    return new Response(bytes, {
      headers: {
        'Content-Type': 'application/pdf',
        'Content-Disposition': 'attachment; filename="test.pdf"',
      },
    })
  })
  const data = response()
  await handler({ method: 'GET', url: '/api/report.pdf/', headers: {} }, data)
  assert.deepEqual(data.body, bytes)
  assert.equal(data.headers.get('content-disposition'), 'attachment; filename="test.pdf"')
  const offline = response()
  await handler({ method: 'GET', url: '/api/health/', headers: {} }, offline)
  assert.equal(offline.statusCode, 502)
})
