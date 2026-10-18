export const DEFAULT_TABLE_NAME = "Babette's Table"

export async function readJson(path) {
  const res = await fetch(path, { headers: { Accept: 'application/json' } })
  if (!res.ok) throw new Error(path + ' ' + res.status)
  const type = res.headers.get('content-type') || ''
  if (!type.includes('application/json')) throw new Error(path + ' not json')
  return res.json()
}

function readFestinSettings() {
  return readJson('/api/settings').then((body) => {
    const raw = body?.tableName ?? body?.table_name
    const tableName = typeof raw === 'string' && raw.trim() ? raw.trim() : DEFAULT_TABLE_NAME
    return { tableName }
  })
}

export function bootKitchen() {
  return readFestinSettings()
}
