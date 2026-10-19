import { CONTEXT_LANES, draftFromSettings, readSaveResult, settingsSaveBody } from './form.js'
import { readPluginSaveResult } from './plugins.js'

async function readJson(res) {
  const type = res.headers.get('content-type') || ''
  if (!type.includes('application/json')) {
    return null
  }
  try {
    return await res.json()
  } catch {
    return null
  }
}

export async function fetchSettings() {
  const res = await fetch('/api/settings', { headers: { Accept: 'application/json' } })
  const body = await readJson(res)
  if (!res.ok) throw new Error((body && body.error) || 'Settings ' + res.status)
  return draftFromSettings(body)
}

export async function saveModelKey(key) {
  const res = await fetch('/api/settings/model-key', {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({ key }),
  })
  const body = await readJson(res)
  return readSaveResult(res.status, body)
}

export async function testModel() {
  const res = await fetch('/api/settings/model-test', {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  const body = await readJson(res)
  return readSaveResult(res.status, body)
}

/** Mint a new inbox bearer key. The plaintext is in body.inboxKey once. */
export async function rotateInboxKey() {
  const res = await fetch('/api/settings/inbox-key', {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  const body = await readJson(res)
  return readSaveResult(res.status, body)
}

export async function saveSettings(draft, expectedUpdatedAt) {
  const res = await fetch('/api/settings', {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(settingsSaveBody(draft, expectedUpdatedAt)),
  })
  const body = await readJson(res)
  return readSaveResult(res.status, body)
}

/** Household context sections live in household_context, not notes. */
export async function fetchContextLanes() {
  const out = {}
  await Promise.all(
    CONTEXT_LANES.map(async (lane) => {
      const res = await fetch('/api/household-context/' + lane.key, {
        headers: { Accept: 'application/json' },
      })
      const body = await readJson(res)
      if (!res.ok) {
        out[lane.key] = { section: lane.key, text: '', updatedAt: null, missing: true }
        return
      }
      const text = String(body?.text || '')
      out[lane.key] = {
        section: lane.key,
        text,
        updatedAt: body?.updatedAt || null,
        missing: !text && body?.updatedAt == null,
      }
    }),
  )
  return out
}

export async function saveContextLane(lane, text, expectedUpdatedAt) {
  const cleaned = String(text || '').trim()
  if (!cleaned) {
    return { ok: false, conflict: false, error: 'Write a short note before saving.', body: null }
  }
  const res = await fetch('/api/household-context/' + lane.key, {
    method: 'PUT',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: cleaned, expectedUpdatedAt: expectedUpdatedAt ?? null }),
  })
  const body = await readJson(res)
  if (res.status === 409) {
    return {
      ok: false,
      conflict: true,
      error: (body && body.error) || 'This section changed. Refresh before editing it.',
      body,
    }
  }
  if (!res.ok) {
    return { ok: false, conflict: false, error: (body && body.error) || 'Could not save.', body }
  }
  return { ok: true, conflict: false, error: null, body }
}

/** Plugin list from GET /api/plugins. */
export async function fetchPlugins() {
  const res = await fetch('/api/plugins', { headers: { Accept: 'application/json' } })
  if (res.status === 404) return { status: 'missing', plugins: [] }
  const body = await readJson(res)
  if (!res.ok) return { status: 'error', plugins: [], error: (body && body.error) || String(res.status) }
  const list = Array.isArray(body?.plugins) ? body.plugins : Array.isArray(body) ? body : []
  return { status: 'ok', plugins: list }
}

export async function putPlugin(pluginId, body) {
  const res = await fetch('/api/plugins/' + encodeURIComponent(pluginId), {
    method: 'PUT',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const payload = await readJson(res)
  return readPluginSaveResult(res.status, payload)
}

export async function callPluginAction(pluginId, action, body = {}) {
  const res = await fetch('/api/plugins/' + encodeURIComponent(pluginId) + '/' + encodeURIComponent(action), {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const payload = await readJson(res)
  if (!res.ok) {
    return { ok: false, error: (payload && payload.error) || 'Action failed (' + res.status + ').', body: payload }
  }
  return { ok: true, error: null, body: payload }
}
