import { readFile } from 'node:fs/promises'
import assert from 'node:assert/strict'
import test from 'node:test'

test('production and synthetic preview use distinct same-origin rewrites', async () => {
  const { rewrites } = JSON.parse(await readFile(new URL('../../vercel.json', import.meta.url), 'utf8'))
  const target = (host, source) => rewrites.find(rule => rule.source === source &&
    (!rule.has || rule.has.some(item => item.type === 'host' && item.value === host))).destination
  for (const source of ['/api/:path*/', '/api/:path*']) {
    assert.equal(new URL(target('datumlex-core.vercel.app', source)).hostname,
      'datumlex-api-real-production.up.railway.app')
    assert.equal(new URL(target('datumlex-core-git-fix-reco-1c680c-pedromattos-projects-d7c0e0fe.vercel.app', source)).hostname,
      'datumlex-api-preview-recovery-preview.up.railway.app')
    assert.match(target('unassigned-build.vercel.app', source), /^\/api\/gateway\?/)
  }
})
