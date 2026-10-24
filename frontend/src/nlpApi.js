const base = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')

export function reportUrl(snapshotId) {
  return `${base}/v2/analysis-snapshots/${encodeURIComponent(snapshotId)}/report/`
}

export async function nlpRequest(path, { signal, body } = {}) {
  let csrfToken
  if (body) {
    const csrf = await fetch(`${base}/auth/csrf/`, { credentials: 'include', signal })
    if (!csrf.ok) throw new Error('Não foi possível iniciar a consulta.')
    const token = await csrf.json()
    csrfToken = token.csrfToken
  }
  const response = await fetch(`${base}/v2/${path}`, {
    method: body ? 'POST' : 'GET', credentials: 'include', signal,
    headers: body ? { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken } : {},
    ...(body ? { body: JSON.stringify(body) } : {}),
  })
  const data = await response.json()
  if (response.status === 401) window.dispatchEvent(new Event('datumlex:session-ended'))
  if (!response.ok) throw new Error(data.error?.message || 'Não foi possível consultar as evidências.')
  const expectedSnapshot = path.match(/^analysis-snapshots\/([^/]+)\//)?.[1]
  if (expectedSnapshot && data.snapshot_id !== expectedSnapshot) throw new Error('A resposta pertence a outro snapshot. Atualize a consulta.')
  if (body && (!data.snapshot_id || !data.context || !data.populations || !data.exclusions)) throw new Error('A API retornou um snapshot inválido.')
  return data
}

export function safeOfficialUrl(value) {
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && !url.username && !url.password &&
      ['stj.jus.br', 'tjdft.jus.br'].some(domain => url.hostname === domain || url.hostname.endsWith(`.${domain}`))
      ? url.href : null
  } catch { return null }
}
