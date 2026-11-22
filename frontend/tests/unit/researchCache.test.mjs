import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createResearchCache } from '../../src/researchCache.js'

test('navigation reuses responses and concurrent requests for identical filters', async () => {
  let calls = 0
  const cache = createResearchCache(async () => ({ calls: ++calls }))
  const first = cache.load('research', { court: 'STJ', start: '2016' })
  assert.equal(first, cache.load('research', { start: '2016', court: 'STJ' }))
  const data = await first
  await cache.load('research/overview', { court: 'STJ' })
  assert.equal(await cache.load('research', { court: 'STJ', start: '2016' }), data)
  assert.equal(calls, 2)
  assert.equal(cache.peek('research', { start: '2016', court: 'STJ' }), data)
})

test('filters, resource, workspace and expiry remain isolated', async () => {
  let clock = 0, calls = 0
  const fetchData = async () => ++calls
  const cache = createResearchCache(fetchData, { ttl: 10, now: () => clock })
  await cache.load('research', { court: 'STJ' })
  await cache.load('research', { court: 'TJDFT' })
  assert.equal(cache.peek('research/sources', { court: 'STJ' }), undefined)
  assert.equal(createResearchCache(fetchData).peek('research', { court: 'STJ' }), undefined)
  clock = 11
  assert.equal(cache.peek('research', { court: 'STJ' }), undefined)
  await cache.load('research', { court: 'STJ' })
  assert.equal(calls, 3)
})

test('failures can be retried and sign out aborts pending requests', async () => {
  let calls = 0, pendingSignal
  const cache = createResearchCache(async (_resource, _filters, signal) => {
    pendingSignal = signal
    if (++calls === 1) throw Error('offline')
    return { ok: true }
  })
  await assert.rejects(cache.load('research', {}), /offline/)
  await cache.load('research', {})
  cache.clear()
  assert.equal(pendingSignal.aborted, true)
  assert.equal(cache.peek('research', {}), undefined)
})

test('completed response count is bounded', async () => {
  const cache = createResearchCache(async () => ({}), { limit: 2 })
  for (const page of [1, 2, 3]) await cache.load('research/sources', { page })
  assert.equal(cache.peek('research/sources', { page: 1 }), undefined)
  assert.ok(cache.peek('research/sources', { page: 3 }))
})
