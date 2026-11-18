import assert from 'node:assert/strict'
import { test } from 'node:test'

import { thesisSummary, thesisTitle } from '../../src/thesisPresentation.js'

test('prioriza o rótulo curto e usa um título padrão quando o texto está ausente', () => {
  assert.equal(thesisTitle({ label: '  Nexo causal  ', titulo: 'Outro título' }), 'Nexo causal')
  assert.equal(thesisTitle({ titulo: 'Culpa exclusiva' }), 'Culpa exclusiva')
  assert.equal(thesisTitle({}), 'Tese sem título')
})

test('reconhece o tema de um enunciado longo mesmo com acentos e maiúsculas', () => {
  const title = 'A inversão do ÔNUS DA PROVA exige a análise das circunstâncias de cada caso concreto.'
  assert.equal(thesisTitle({ title }), 'Ônus da prova')
})

test('abrevia enunciados sem tema reconhecido em um limite de palavra', () => {
  const title = 'A revisão das circunstâncias probatórias apresentadas exige novo exame de todos os fatos.'
  assert.equal(thesisTitle({ title }), 'A revisão das circunstâncias probatórias apresentadas exige…')
})

test('reduz títulos com sete palavras longas sem cortar uma palavra ao meio', () => {
  const title = 'A avaliação extraordinária das circunstâncias probatórias apresentadas exige novo exame de todos os fatos.'
  assert.equal(thesisTitle({ title }), 'A avaliação extraordinária das circunstâncias probatórias…')
})

test('prioriza o resumo explícito e remove espaços nas extremidades', () => {
  assert.equal(thesisSummary({ summary: '  Resumo informado.  ', title: 'Enunciado.' }), 'Resumo informado.')
})

test('extrai a primeira frase completa preservando a negação e a condição', () => {
  const title = 'Não há dano moral sem prova das circunstâncias concretas. A análise exige revisão.'
  assert.equal(thesisSummary({ summary: ' ', title }), 'Não há dano moral sem prova das circunstâncias concretas.')
})

test('usa o enunciado inteiro quando não encontra um limite de frase', () => {
  assert.equal(thesisSummary({ label: '  Análise das circunstâncias concretas  ' }), 'Análise das circunstâncias concretas')
  assert.equal(thesisSummary({}), '')
})
