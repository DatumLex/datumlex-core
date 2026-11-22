import assert from 'node:assert/strict'
import { test } from 'node:test'
import { loadNotebook, notebookKey, saveNotebook } from '../../src/notebookStorage.js'

function storage() {
  const values = new Map()
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }
}
const source = { id: 'F42', kind: 'precedent', title: 'Precedente com acentuação', origin: 'Pangea/BNP',
  excerpt: 'Trecho da fonte', date: null, url: 'https://example.org/documento', authors: [] }

test('restaura as fontes após recriar o estado da página e mantém remoções', () => {
  const local = storage(), key = notebookKey(1, ['STJ', 'TJDFT'])
  assert.equal(saveNotebook(key, { F42: source }, local), '')
  assert.deepEqual(loadNotebook(key, local), { items: { F42: source }, error: '' })
  saveNotebook(key, {}, local)
  assert.deepEqual(loadNotebook(key, local).items, {})
})

test('separa contas e escopos de autorização sem depender da ordem dos tribunais', () => {
  const local = storage()
  saveNotebook(notebookKey(1, ['STJ', 'TJDFT']), { F42: source }, local)
  assert.deepEqual(loadNotebook(notebookKey(2, ['STJ', 'TJDFT']), local).items, {})
  assert.deepEqual(loadNotebook(notebookKey(1, ['STJ']), local).items, {})
  assert.equal(notebookKey(1, ['TJDFT', 'STJ']), notebookKey(1, ['STJ', 'TJDFT']))
  assert.equal(notebookKey(undefined), null)
})

test('trata armazenamento corrompido, bloqueado ou cheio sem quebrar a página', () => {
  assert.ok(loadNotebook('key', { getItem: () => '{invalid' }).error)
  assert.ok(loadNotebook('key', { getItem: () => { throw new Error('blocked') } }).error)
  assert.ok(saveNotebook('key', {}, { setItem: () => { throw new Error('quota') } }))
  assert.ok(saveNotebook(null, {}))
})

test('descarta registros inválidos e não restaura links com execução de scripts', () => {
  const local = storage()
  local.setItem('key', JSON.stringify({ version: 1, items: [null, { id: 'bad' }, { ...source, url: 'javascript:alert(1)' }] }))
  const restored = loadNotebook('key', local)
  assert.deepEqual(Object.keys(restored.items), ['F42'])
  assert.equal(restored.items.F42.url, '')
})
