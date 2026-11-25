import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'

import {
  bibliographyLine,
  dateDisplay,
  publisherLine,
  rowSubtitle,
  sourceKindLabel,
  tpuDisplay,
} from '../../src/sourcePresentation.js'

test('formata metadados completos de doutrina sem inventar dia de publicação', () => {
  const doc = {
    kind: 'doctrine',
    source_kind: 'artigo',
    origin: 'Senado Federal',
    date: null,
    date_kind: 'publication_period',
    publication_period: 'jan./mar. 2024',
    publication_year: 2024,
    bibliography: {
      publication: 'Revista de Informação Legislativa: RIL',
      publisher: 'Senado Federal',
      place: 'Brasília, DF',
      volume: 61,
      issue: 241,
      pages: '237–254',
      period: 'jan./mar. 2024',
      year: 2024,
    },
  }
  assert.equal(sourceKindLabel(doc), 'Artigo')
  assert.deepEqual(dateDisplay(doc), { label: 'Período de publicação', value: 'jan./mar. 2024', exact: false })
  assert.equal(bibliographyLine(doc), 'Revista de Informação Legislativa: RIL · v. 61 · n. 241 · p. 237–254')
  assert.equal(publisherLine(doc), 'Senado Federal · Brasília, DF')
  assert.equal(rowSubtitle(doc), 'Artigo · Senado Federal · jan./mar. 2024')
})

test('respeita campos ausentes sem fabricar data, bibliografia ou TPU', () => {
  const sparse = {
    kind: 'doctrine',
    source_kind: 'artigo',
    origin: 'Editora Sintética',
    date: null,
    publication_year: 2020,
  }
  assert.deepEqual(dateDisplay(sparse), { label: 'Ano de publicação', value: '2020', exact: false })
  assert.equal(bibliographyLine(sparse), '')
  assert.equal(publisherLine(sparse), '')
  assert.equal(tpuDisplay(sparse), null)

  assert.equal(dateDisplay({ kind: 'jurisprudence', date: null }), null)
})

test('distingue tipo de data e origem da TPU em jurisprudência e precedentes', () => {
  const datajudCase = {
    kind: 'jurisprudence',
    source_kind: 'acordao',
    court: 'TJDFT',
    judging_body: '8ª Turma Cível',
    date: '2024-12-10',
    date_kind: 'decision_date',
    tpu: {
      state: 'verified_linked_datajud',
      codes: [10435, 10439],
      label: 'TPU derivada do cadastro DataJud vinculado',
    },
  }
  assert.deepEqual(dateDisplay(datajudCase), { label: 'Julgamento', value: '10/12/2024', exact: true })
  assert.deepEqual(tpuDisplay(datajudCase), {
    label: 'TPU derivada do cadastro DataJud vinculado',
    codes: '10435, 10439',
    state: 'verified_linked_datajud',
  })
  assert.equal(rowSubtitle(datajudCase), 'Acórdão · TJDFT · 8ª Turma Cível · 10/12/2024')

  const pubCase = {
    kind: 'jurisprudence',
    source_kind: 'acordao',
    court: 'STJ',
    date: '2011-09-08',
    date_kind: 'publication_date',
    tpu: {
      state: 'verified_official_label',
      codes: [10433],
      label: 'TPU mapeada do rótulo oficial',
    },
  }
  assert.deepEqual(dateDisplay(pubCase), { label: 'Publicação', value: '08/09/2011', exact: true })
  assert.equal(tpuDisplay(pubCase).label, 'TPU mapeada do rótulo oficial')

  const officialPrecedent = {
    kind: 'precedent',
    source_kind: 'recurso_repetitivo',
    official_tpu: [10441],
  }
  assert.equal(sourceKindLabel(officialPrecedent), 'Tema repetitivo')
  assert.equal(tpuDisplay(officialPrecedent).label, 'TPU oficial da ficha')
  assert.equal(tpuDisplay(officialPrecedent).codes, '10441')
})

test('ResearchWorkspace e CorpusPanel exibem metadados e mantêm bloqueio de texto integral', async () => {
  for (const rel of ['../../src/ResearchWorkspace.jsx', '../../src/CorpusPanel.jsx']) {
    const source = await readFile(new URL(rel, import.meta.url), 'utf8')
    assert.match(source, /bibliographyLine/)
    assert.match(source, /tpuDisplay/)
    assert.match(source, /license/)
    assert.match(source, /O texto da fonte está disponível apenas na publicação de origem/)
    assert.doesNotMatch(source, /archive_provenance/)
  }
})
