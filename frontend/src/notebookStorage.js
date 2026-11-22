const message = 'Não foi possível salvar o caderno neste navegador. As alterações ficam apenas nesta página até o armazenamento estar disponível.'
const kinds = new Set(['jurisprudence', 'precedent', 'doctrine', 'link'])

export function notebookKey(userId, courts = []) {
  if (userId === undefined || userId === null) return null
  return `datumlex:notebook:v1:${encodeURIComponent(String(userId))}:${[...new Set(courts)].sort().join(',')}`
}

function normalizeSource(value) {
  if (!value || typeof value !== 'object' || typeof value.id !== 'string'
    || !value.id || !kinds.has(value.kind) || typeof value.title !== 'string') return null
  let url = ''
  try {
    const parsed = new URL(value.url)
    if (['https:', 'http:'].includes(parsed.protocol) && !parsed.username && !parsed.password) url = parsed.href
  } catch { /* Missing or invalid source URLs are not links. */ }
  return {
    id: value.id, kind: value.kind, title: value.title,
    origin: typeof value.origin === 'string' ? value.origin : '',
    date: typeof value.date === 'string' ? value.date : null,
    excerpt: typeof value.excerpt === 'string' ? value.excerpt : '',
    url,
    authors: Array.isArray(value.authors) ? value.authors.filter((v) => typeof v === 'string') : [],
    ...(typeof value.relation === 'string' ? { relation: value.relation } : {}),
  }
}

export function loadNotebook(key, storage) {
  if (!key) return { items: {}, error: message }
  try {
    const raw = (storage ?? globalThis.localStorage).getItem(key)
    if (!raw) return { items: {}, error: '' }
    const data = JSON.parse(raw)
    if (data?.version !== 1 || !Array.isArray(data.items)) throw new Error('Invalid notebook format')
    const items = data.items.map(normalizeSource).filter(Boolean)
    return { items: Object.fromEntries(items.map((item) => [item.id, item])), error: '' }
  } catch {
    return { items: {}, error: message }
  }
}

export function saveNotebook(key, items, storage) {
  if (!key) return message
  try {
    const documents = Object.values(items).map(normalizeSource).filter(Boolean)
    const target = storage ?? globalThis.localStorage
    target.setItem(key, JSON.stringify({ version: 1, items: documents }))
    return ''
  } catch {
    return message
  }
}
