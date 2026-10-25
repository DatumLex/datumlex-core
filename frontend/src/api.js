const base = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')

export async function downloadReport(filters) {
  const response = await fetch(`${base}/report.pdf/?${new URLSearchParams(filters)}`, { credentials: 'include' })
  if (response.status === 401) window.dispatchEvent(new Event('datumlex:session-ended'))
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(data.error?.message || 'Não foi possível gerar o PDF. Tente novamente.')
  }
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `datumlex-${filters.start}-${filters.end}.pdf`
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export async function getData(resource, filters, signal) {
  const query = new URLSearchParams({ court: 'TJDFT', ...filters })
  const response = await fetch(`${base}/${resource}/?${query}`, { signal, credentials: 'include' })
  if (response.status === 401) window.dispatchEvent(new Event('datumlex:session-ended'))
  if (response.status === 403) throw new Error('Você não possui permissão para esta consulta. Atualize a página para revisar seu acesso.')
  if (!response.ok) throw new Error(response.status === 400
    ? 'O período informado não é válido. Confira as datas e tente novamente.'
    : 'Não foi possível consultar os dados. Verifique se o backend está rodando e tente novamente.')
  const data = await response.json()
  if (!data || typeof data !== 'object') throw new Error('A API retornou uma resposta inválida.')
  return data
}
