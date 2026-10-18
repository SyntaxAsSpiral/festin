export const DEFAULT_TABLE_NAME = "Babette's Table"

function pickName(data) {
  if (!data || typeof data !== 'object') return ''
  const raw = data.tableName ?? data.table_name
  return typeof raw === 'string' ? raw.trim() : ''
}

export async function fetchTableName(signal) {
  const res = await fetch('/api/settings', {
    signal,
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) throw new Error('settings ' + res.status)
  const type = res.headers.get('content-type') || ''
  if (!type.includes('application/json')) throw new Error('settings not json')
  const name = pickName(await res.json())
  return name || DEFAULT_TABLE_NAME
}
