/**
 * Pure presentation helpers for approved legal source metadata.
 * Never fabricates missing dates, DOI, TPU codes, or bibliographic details.
 */

export const SOURCE_KIND_LABELS = {
  enunciado_sumular: 'Súmula',
  recurso_repetitivo: 'Tema repetitivo',
  acordao: 'Acórdão',
  artigo: 'Artigo',
  doctrine_article: 'Artigo',
  doctrine_collection: 'Coletânea',
  precedent_reference: 'Referência de precedente',
  full_text: 'Inteiro teor',
  ementa: 'Ementa',
  publication_excerpt: 'Publicação',
}

export const CATEGORY_LABELS = {
  jurisprudence: 'Decisão',
  precedent: 'Precedente',
  doctrine: 'Doutrina',
  link: 'Vínculo em ementa',
}

export function formatIsoDate(value) {
  if (!value || typeof value !== 'string') return ''
  const parts = value.slice(0, 10).split('-')
  return parts.length === 3 ? parts.reverse().join('/') : value
}

export function sourceKindLabel(doc) {
  return (
    SOURCE_KIND_LABELS[doc?.source_kind || doc?.content_kind] ||
    CATEGORY_LABELS[doc?.kind || doc?.category] ||
    doc?.source_kind ||
    doc?.content_kind ||
    'Fonte'
  )
}

export function dateDisplay(doc) {
  if (!doc) return null
  if (doc.date) {
    const label =
      doc.date_kind === 'decision_date'
        ? 'Julgamento'
        : doc.date_kind === 'publication_date'
          ? 'Publicação'
          : 'Data da fonte'
    return { label, value: formatIsoDate(doc.date), exact: true }
  }
  const period = doc.publication_period || doc.bibliography?.period
  if (period) {
    return { label: 'Período de publicação', value: period, exact: false }
  }
  const year = doc.publication_year ?? doc.bibliography?.year
  if (Number.isInteger(year)) {
    return { label: 'Ano de publicação', value: String(year), exact: false }
  }
  return null
}

export function bibliographyLine(doc) {
  const bib = doc?.bibliography
  if (!bib || typeof bib !== 'object') return ''
  const parts = []
  if (bib.publication) parts.push(bib.publication)
  if (bib.volume != null && bib.volume !== '') parts.push(`v. ${bib.volume}`)
  if (bib.issue != null && bib.issue !== '') parts.push(`n. ${bib.issue}`)
  if (bib.edition) parts.push(bib.edition)
  if (bib.pages) parts.push(`p. ${bib.pages}`)
  if (!parts.length && bib.locator) parts.push(bib.locator)
  return parts.join(' · ')
}

export function publisherLine(doc) {
  const bib = doc?.bibliography
  if (!bib || typeof bib !== 'object') return ''
  return [bib.publisher, bib.place].filter(Boolean).join(' · ')
}

export function tpuDisplay(doc) {
  if (doc?.tpu?.codes?.length) {
    return {
      label: doc.tpu.label || 'TPU verificada',
      codes: doc.tpu.codes.join(', '),
      state: doc.tpu.state || '',
    }
  }
  if (doc?.official_tpu?.length) {
    return {
      label: 'TPU oficial da ficha',
      codes: doc.official_tpu.join(', '),
      state: 'verified_official_code',
    }
  }
  return null
}

export function rowSubtitle(doc) {
  const parts = [sourceKindLabel(doc), doc?.court || doc?.origin]
  if (doc?.judging_body) parts.push(doc.judging_body)
  const when = dateDisplay(doc)
  if (when) parts.push(when.value)
  return parts.filter(Boolean).join(' · ')
}
