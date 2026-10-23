/** Settings form mapping: API body ↔ draft, and the 409 conflict path. */

import { DEFAULT_WET_BAND, clampWetBand } from '../chat/ink/constants.js'

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
  { key: 'household', label: 'Household' },
  { key: 'preferences', label: 'Preferences' },
  { key: 'restrictions', label: 'Restrictions' },
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

/** Map GET /api/settings into the form draft. Model is { baseUrl, name, keySet, keySource }. */
export function draftFromSettings(body) {
  const weather = body?.weather && typeof body.weather === 'object' ? body.weather : {}
  const nested = body?.model && typeof body.model === 'object' ? body.model : null
  const modelBaseUrl =
    (nested && pick(nested, 'baseUrl', 'base_url')) ||
    pick(body, 'modelBaseUrl', 'model_base_url', 'baseUrl', 'base_url') ||
    OPENROUTER_BASE
  const named = nested && typeof nested.name === 'string' ? nested.name : undefined
  const modelName = named ?? pick(body, 'modelName', 'model_name') ?? (typeof body?.model === 'string' ? body.model : '')
  const keySource = cleanKeySource(nested ? nested.keySource : body?.keySource)
  const keySet = Boolean(nested ? nested.keySet : body?.keySet) || keySource === 'file'
  const inbox = body?.inbox && typeof body.inbox === 'object' ? body.inbox : {}
  return {
    tableName: String(body?.tableName || body?.table_name || DEFAULT_TABLE).trim() || DEFAULT_TABLE,
    weekStart: cleanWeek(body?.weekStart || body?.week_start_day || 'sat'),
    weatherLocation: String(weather.location || body?.weatherLocation || '').trim(),
    modelName: String(modelName).trim(),
    modelBaseUrl: String(modelBaseUrl).trim().replace(/\/+$/, '') || OPENROUTER_BASE,
    keySet,
    keySource,
    inboxEnabled: inbox.enabled !== false && body?.inboxEnabled !== false,
    inboxAddress: String(inbox.address || body?.inboxAddress || '').trim(),
    inboxKeySet: Boolean(inbox.keySet ?? body?.inboxKeySet),
    chatWetBand: clampWetBand(pick(body, 'chatWetBand', 'chat_wet_band'), DEFAULT_WET_BAND),
    updatedAt: body?.updatedAt || body?.updated_at || null,
  }
}

/** Body for POST /api/settings. The key is a separate write and never rides along. */
export function settingsSaveBody(draft, expectedUpdatedAt) {
  const body = {
    tableName: String(draft.tableName || '').trim() || DEFAULT_TABLE,
    weekStart: cleanWeek(draft.weekStart),
    weatherLocation: String(draft.weatherLocation || '').trim(),
    modelName: String(draft.modelName || '').trim(),
    modelBaseUrl: String(draft.modelBaseUrl || '').trim().replace(/\/+$/, '') || OPENROUTER_BASE,
    inboxEnabled: draft.inboxEnabled !== false,
    chatWetBand: clampWetBand(draft.chatWetBand, DEFAULT_WET_BAND),
  }
  if (expectedUpdatedAt != null) {
    body.expectedUpdatedAt = expectedUpdatedAt
    body.expected_updated_at = expectedUpdatedAt
  }
  return body
}

/** Copyable block shown once after New key. */
export function inboxKeyBlock(payload) {
  const key = String(payload?.key || '').trim()
  const address = String(payload?.address || '').trim()
  const example = String(payload?.exampleCurl || '').trim()
  if (!key) return ''
  const lines = [
    'Incoming recipes — give this to an outside agent',
    address ? `URL: ${address}` : null,
    `Key: ${key}`,
    example ? `Example:\n${example}` : null,
  ].filter(Boolean)
  return lines.join('\n')
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

function cleanKeySource(value) {
  const source = String(value || '').trim().toLowerCase()
  return source === 'file' || source === 'env' || source === 'none' ? source : 'none'
}


