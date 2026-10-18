/** Settings form mapping: API body ↔ draft, and the 409 conflict path. */

export const SETTINGS_TABS = ['model', 'context', 'plugins']
export const OPENROUTER_BASE = 'https://openrouter.ai/api/v1'
export const WEEK_STARTS = [
  { value: 'sat', label: 'Saturday' },
  { value: 'sun', label: 'Sunday' },
  { value: 'mon', label: 'Monday' },
  { value: 'tue', label: 'Tuesday' },
  { value: 'wed', label: 'Wednesday' },
  { value: 'thu', label: 'Thursday' },
  { value: 'fri', label: 'Friday' },
]
export const CONTEXT_LANES = [
  { id: 'context-household', key: 'household', label: 'Household' },
  { id: 'context-preferences', key: 'preferences', label: 'Preferences' },
  { id: 'context-restrictions', key: 'restrictions', label: 'Restrictions' },
]

const DEFAULT_TABLE = "Babette's Table"

export function parseSettingsTab(raw) {
  const tab = String(raw || '').trim().toLowerCase()
  return SETTINGS_TABS.includes(tab) ? tab : null
}

export function providerOf(baseUrl) {
  try {
    const host = new URL(String(baseUrl || '').trim()).hostname
    return host === 'openrouter.ai' ? 'openrouter' : 'local'
  } catch {
    return 'local'
  }
}

export function baseUrlForProvider(provider, current) {
  if (provider === 'openrouter') return OPENROUTER_BASE
  const now = String(current || '').trim()
  if (!now || providerOf(now) === 'openrouter') return ''
  return now
}

/** Map GET /api/settings (and optional model fields) into the form draft. */
export function draftFromSettings(body) {
  const weather = body?.weather && typeof body.weather === 'object' ? body.weather : {}
  const modelBaseUrl =
    pick(body, 'modelBaseUrl', 'model_base_url', 'baseUrl', 'base_url') || OPENROUTER_BASE
  const modelName = pick(body, 'modelName', 'model_name', 'model') || ''
  return {
    tableName: String(body?.tableName || body?.table_name || DEFAULT_TABLE).trim() || DEFAULT_TABLE,
    dinnerHour: normalizeHour(body?.dinnerHour || body?.dinner_hour || '17:30'),
    weekStart: cleanWeek(body?.weekStart || body?.week_start_day || 'sat'),
    weatherLocation: String(weather.location || body?.weatherLocation || '').trim(),
    modelName: String(modelName).trim(),
    modelBaseUrl: String(modelBaseUrl).trim().replace(/\/+$/, '') || OPENROUTER_BASE,
    updatedAt: body?.updatedAt || body?.updated_at || null,
  }
}

/** Body for POST /api/settings. Model fields ride along for when the API accepts them. */
export function settingsSaveBody(draft, expectedUpdatedAt) {
  const body = {
    tableName: String(draft.tableName || '').trim() || DEFAULT_TABLE,
    dinnerHour: normalizeHour(draft.dinnerHour),
    weekStart: cleanWeek(draft.weekStart),
    weatherLocation: String(draft.weatherLocation || '').trim(),
    modelName: String(draft.modelName || '').trim(),
    modelBaseUrl: String(draft.modelBaseUrl || '').trim().replace(/\/+$/, '') || OPENROUTER_BASE,
  }
  if (expectedUpdatedAt != null) {
    body.expectedUpdatedAt = expectedUpdatedAt
    body.expected_updated_at = expectedUpdatedAt
  }
  return body
}

export function lanePreview(text) {
  const line = String(text || '')
    .split(/\n/)
    .map((s) => s.trim())
    .find(Boolean)
  if (!line) return 'Not set'
  return line.length > 72 ? line.slice(0, 71) + '…' : line
}

/** Turn a fetch response into either the saved body or a conflict/error. */
export function readSaveResult(status, body) {
  if (status === 409) {
    return {
      ok: false,
      conflict: true,
      error: (body && body.error) || 'Settings changed. Refresh before saving.',
      body: body || null,
    }
  }
  if (status < 200 || status >= 300) {
    return {
      ok: false,
      conflict: false,
      error: (body && body.error) || 'Could not save settings (' + status + ').',
      body: body || null,
    }
  }
  return { ok: true, conflict: false, error: null, body }
}

function pick(obj, ...keys) {
  if (!obj || typeof obj !== 'object') return undefined
  for (const key of keys) {
    if (key in obj && obj[key] != null && obj[key] !== '') return obj[key]
  }
  return undefined
}

function cleanWeek(value) {
  const day = String(value || 'sat').trim().toLowerCase()
  return WEEK_STARTS.some((item) => item.value === day) ? day : 'sat'
}

function normalizeHour(value) {
  const text = String(value || '').trim()
  const match = /^(\d{1,2}):(\d{2})(?::\d{2})?$/.exec(text)
  if (!match) return '17:30'
  const hour = Math.min(23, Math.max(0, Number(match[1])))
  let minute = Math.min(59, Math.max(0, Number(match[2])))
  minute = Math.round(minute / 15) * 15
  if (minute === 60) return String((hour + 1) % 24).padStart(2, '0') + ':00'
  return String(hour).padStart(2, '0') + ':' + String(minute).padStart(2, '0')
}
