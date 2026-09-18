const base = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')

export async function getData(resource, filters, signal) {
  const query = new URLSearchParams({ court: 'TJDFT', ...filters })
  const response = await fetch(`${base}/${resource}/?${query}`, { signal })
  if (!response.ok) throw new Error(response.status === 400
    ? 'O período informado não é válido. Confira as datas e tente novamente.'
    : 'Não foi possível consultar os dados. Verifique se o backend está rodando e tente novamente.')
  const data = await response.json()
  if (!data || typeof data !== 'object') throw new Error('A API retornou uma resposta inválida.')
  return data
}
