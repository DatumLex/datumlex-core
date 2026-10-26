export function formatProcessIdentifier(value) {
  const identifier = String(value || '').trim()
  return /^\d{20}$/.test(identifier)
    ? identifier.replace(/^(\d{7})(\d{2})(\d{4})(\d)(\d{2})(\d{4})$/, '$1-$2.$3.$4.$5.$6')
    : identifier
}
