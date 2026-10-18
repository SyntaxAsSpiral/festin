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

export async function saveSettings(draft, expectedUpdatedAt) {
  const res = await fetch('/api/settings', {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(settingsSaveBody(draft, expectedUpdatedAt)),
  })
  const body = await readJson(res)
  return readSaveResult(res.status, body)
}

/** Context lanes live as notes (context-household, …). Missing notes are empty. */
export async function fetchContextLanes() {
  const out = {}
  await Promise.all(
    CONTEXT_LANES.map(async (lane) => {
      const res = await fetch('/api/notes/' + lane.id, { headers: { Accept: 'application/json' } })
      if (res.status === 404) {
        out[lane.key] = { id: lane.id, text: '', updatedAt: null, missing: true }
        return
      }
      const body = await readJson(res)
      if (!res.ok) {
        out[lane.key] = { id: lane.id, text: '', updatedAt: null, missing: true }
        return
      }
      out[lane.key] = {
        id: lane.id,
        text: String(body?.text || ''),
        updatedAt: body?.updatedAt || null,
        missing: false,
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
  if (lane.missing) {
    const res = await fetch('/api/notes', {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: lane.id, type: lane.key, text: cleaned, color: 'none' }),
    })
    const body = await readJson(res)
    if (!res.ok) {
      return {
        ok: false,
        conflict: res.status === 409,
        error: (body && body.error) || 'Could not create the note.',
        body,
      }
    }
    return { ok: true, conflict: false, error: null, body }
  }
  const res = await fetch('/api/notes/' + lane.id, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: cleaned, expectedUpdatedAt }),
  })
  const body = await readJson(res)
  if (res.status === 409) {
    return {
      ok: false,
      conflict: true,
      error: (body && body.error) || 'This note changed. Refresh before editing it.',
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
