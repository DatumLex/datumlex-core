export function thesisTitle(group) {
  const text = (group.label || group.titulo || group.title || '').trim()
  if (text.length <= 65 && text.split(/\s+/).length <= 9) return text || 'Tese sem título'
  const normalized = text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
  const themes = [
    [/cadastro.*inadimpl|inscricao.*devedor|negativacao/, 'Inscrição em cadastro de inadimplentes'],
    [/responsabilidade objetiva/, 'Responsabilidade objetiva'],
    [/nexo causal/, 'Nexo causal'],
    [/dano[s]? mora/, 'Dano moral'],
    [/culpa exclusiva/, 'Culpa exclusiva'],
    [/prescri/, 'Prazo de prescrição'],
    [/onus da prova/, 'Ônus da prova'],
  ]
  for (const [pattern, title] of themes) if (pattern.test(normalized)) return title
  const words = text.split(/\s+/)
  let title = words.slice(0, 7).join(' ')
  if (title.length > 62) title = title.slice(0, 59).replace(/\s+\S*$/, '')
  return `${title.replace(/[.,;:—-]+$/, '')}…`
}

export function thesisSummary(group) {
  if (typeof group.summary === 'string' && group.summary.trim()) return group.summary.trim()
  const text = (group.title || group.label || group.titulo || '').trim()
  // Extract a complete sentence; retain legal qualifications in the original below.
  return text.match(/^.*?[.!?](?=\s+[A-ZÀ-Ú]|$)/s)?.[0] || text
}
