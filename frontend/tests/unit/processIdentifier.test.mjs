import assert from 'node:assert/strict'
import { test } from 'node:test'

import { formatProcessIdentifier } from '../../src/processIdentifier.js'

test('formata os 20 dígitos no padrão CNJ e preserva zeros à esquerda', () => {
  assert.equal(formatProcessIdentifier(' 00000017820168240000 '), '0000001-78.2016.8.24.0000')
})

test('preserva identificadores já formatados e referências de outro tipo', () => {
  assert.equal(formatProcessIdentifier('0000001-78.2016.8.24.0000'), '0000001-78.2016.8.24.0000')
  assert.equal(formatProcessIdentifier(' REsp 123/DF '), 'REsp 123/DF')
  assert.equal(formatProcessIdentifier('4009173782016824000'), '4009173782016824000')
})

test('retorna texto vazio para um identificador ausente ou em branco', () => {
  assert.equal(formatProcessIdentifier(undefined), '')
  assert.equal(formatProcessIdentifier(null), '')
  assert.equal(formatProcessIdentifier('   '), '')
})
