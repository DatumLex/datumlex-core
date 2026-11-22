// One cache per mounted workspace: never persisted or shared between accounts.
export function createResearchCache(fetchData, { ttl = 300000, limit = 24, now = Date.now } = {}) {
  const entries = new Map()
  const keyFor = (resource, filters) => resource + '?' + new URLSearchParams(
    Object.entries(filters).sort(([a], [b]) => a.localeCompare(b)),
  )
  function peek(resource, filters) {
    const entry = entries.get(keyFor(resource, filters))
    return entry && entry.expires > now() ? entry.data : undefined
  }
  function load(resource, filters) {
    const key = keyFor(resource, filters)
    const previous = entries.get(key)
    if (previous && (previous.pending || previous.expires > now())) return previous.promise
    const controller = new AbortController()
    const entry = { controller, pending: true }
    entries.set(key, entry)
    entry.promise = Promise.resolve().then(() => fetchData(resource, filters, controller.signal))
      .then((data) => {
        entry.pending = false
        entry.data = data
        entry.expires = now() + ttl
        for (const [oldKey, old] of entries) {
          if (entries.size <= limit) break
          if (!old.pending) entries.delete(oldKey)
        }
        return data
      }, (error) => {
        if (entries.get(key) === entry) entries.delete(key)
        throw error
      })
    return entry.promise
  }
  function clear() {
    for (const entry of entries.values()) entry.controller.abort()
    entries.clear()
  }
  return { load, peek, clear }
}
