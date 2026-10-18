export const DEFAULT_TABLE_NAME = "Babette's Table"

// Boot reader. 'live' is the kitchen on :8876. Switch to 'festin' when
// this repo's backend serves GET /api/settings ({ tableName }).
const KITCHEN = 'live'

let liveBody = null

async function readJson(path) {
  const res = await fetch(path, { headers: { Accept: 'application/json' } })
  if (!res.ok) throw new Error(path + ' ' + res.status)
  const type = res.headers.get('content-type') || ''
  if (!type.includes('application/json')) throw new Error(path + ' not json')
  return res.json()
}

// One GET /api/state. Chat reads this same promise; do not fetch the body again.
export function liveState() {
  if (!liveBody) {
    liveBody = readJson('/api/state').catch((err) => {
      liveBody = null
      throw err
    })
  }
  return liveBody
}

function nameFromFamily(body) {
  const family = body?.state?.settings?.family
  const text = typeof family === 'string' ? family.trim() : ''
  return text ? text + ' Table' : DEFAULT_TABLE_NAME
}

function readFestinSettings() {
  return readJson('/api/settings').then((body) => {
    const raw = body?.tableName ?? body?.table_name
    const tableName = typeof raw === 'string' && raw.trim() ? raw.trim() : DEFAULT_TABLE_NAME
    return { tableName }
  })
}

export function bootKitchen() {
  if (KITCHEN === 'festin') return readFestinSettings()
  return liveState().then((body) => ({ tableName: nameFromFamily(body) }))
}
