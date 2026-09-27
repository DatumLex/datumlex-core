const base = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')
let csrfToken = ''

export async function authRequest(path, method = 'GET', body) {
  if (method !== 'GET' && !csrfToken) await authRequest('auth/csrf')
  let response
  try {
    response = await fetch(`${base}/${path}/`, {
      method, credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...(method !== 'GET' ? { 'X-CSRFToken': csrfToken } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}),
    })
  } catch { throw new Error('Não foi possível conectar ao servidor. Tente novamente.') }
  const data = await response.json().catch(() => ({}))
  if (data.csrfToken) csrfToken = data.csrfToken
  if (!response.ok) {
    const error = new Error(data.error?.message || 'Não foi possível concluir a operação. Tente novamente.')
    error.status = response.status
    if (response.status === 401) window.dispatchEvent(new Event('datumlex:session-ended'))
    throw error
  }
  return data
}
