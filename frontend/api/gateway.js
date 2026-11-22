/**
 * Same-origin gateway for the Django API. Only the configured HTTPS host is
 * reachable, and backend-generated redirects are returned to the browser.
 */
const allowedMethods = new Set(['GET', 'HEAD', 'POST', 'PATCH', 'PUT', 'DELETE', 'OPTIONS'])
const requestHeaders = ['accept', 'content-type', 'cookie', 'origin', 'referer', 'x-csrftoken']
const responseHeaders = ['content-type', 'content-disposition', 'vary', 'retry-after', 'allow']

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'private, no-store')
  if (!allowedMethods.has(req.method)) {
    res.setHeader('Allow', [...allowedMethods].join(', '))
    return res.status(405).end()
  }
  const backend = process.env.DATUMLEX_RAILWAY_ORIGIN
  if (!backend || !/^https:\/\/[a-z0-9.-]+(?::\d+)?$/i.test(backend)) {
    return res.status(503).json({ error: { message: 'Serviço de pesquisa indisponível.' } })
  }
  const incoming = new URL(req.url, 'https://datumlex.invalid')
  if (!incoming.pathname.startsWith('/api/')) return res.status(404).end()
  const isRewriteTarget = /^\/api\/gateway\/?$/.test(incoming.pathname)
  const paths = incoming.searchParams.getAll('datumlex_path')
  const route = isRewriteTarget ? (paths.length === 1 ? paths[0] : '') : incoming.pathname.slice(5)
  if (!/^[a-z0-9_-][a-z0-9_./-]*$/i.test(route) || route.split('/').includes('..')) {
    return res.status(404).end()
  }
  const destination = new URL(backend)
  destination.pathname = '/api/' + route.replace(/\/*$/, '/')
  incoming.searchParams.delete('datumlex_path')
  destination.search = incoming.search
  const headers = new Headers()
  for (const key of requestHeaders) {
    const value = req.headers[key]
    if (typeof value === 'string') headers.set(key, value)
  }
  try {
    const body = ['GET', 'HEAD', 'OPTIONS'].includes(req.method) || req.body == null
      ? undefined
      : typeof req.body === 'string' || Buffer.isBuffer(req.body)
        ? req.body
        : JSON.stringify(req.body)
    const response = await fetch(destination, {
      method: req.method, headers, body, redirect: 'manual', signal: AbortSignal.timeout(45_000),
    })
    for (const key of responseHeaders) {
      const value = response.headers.get(key)
      if (value) res.setHeader(key, value)
    }
    const location = response.headers.get('location')
    if (location) {
      const resolved = new URL(location, destination)
      if (resolved.origin === destination.origin && resolved.pathname.startsWith('/api/')) {
        res.setHeader('Location', resolved.pathname + resolved.search)
      }
    }
    const cookies = response.headers.getSetCookie()
    if (cookies.length) res.setHeader('Set-Cookie', cookies)
    if (req.method === 'HEAD' || response.status === 204 || response.status === 304) {
      return res.status(response.status).end()
    }
    return res.status(response.status).send(Buffer.from(await response.arrayBuffer()))
  } catch {
    return res.status(502).json({ error: { message: 'Não foi possível acessar o serviço de pesquisa.' } })
  }
}
