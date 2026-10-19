/** Schema → field descriptors for a plugin settings panel. */

const SECRET_KEYS = new Set(['token', 'apiKey', 'api_key', 'secret', 'password'])

export function isSecretField(field) {
  if (!field || typeof field !== 'object') return false
  if (field.secret === true) return true
  if (field.type === 'secret' || field.type === 'token' || field.type === 'password') return true
  return SECRET_KEYS.has(String(field.key || ''))
}

export function secretState(value) {
  return String(value || '').length > 0 ? 'set' : 'not set'
}

/** Normalize one schema field into a UI descriptor. */
export function fieldFromSchema(field) {
  if (!field || typeof field !== 'object' || !field.key) return null
  const key = String(field.key)
  const label = String(field.label || key)
  const type = String(field.type || 'string')
  const secret = isSecretField(field)
  const base = {
    key,
    label,
    type: secret ? 'secret' : type,
    secret,
    default: field.default,
  }
  if (Array.isArray(field.enum) && field.enum.length) {
    const choices = Array.isArray(field.choices) ? field.choices : []
    const byId = new Map(choices.map((row) => [row.id, row]))
    return {
      ...base,
      type: 'enum',
      secret: false,
      options: field.enum.map((id) => {
        const row = byId.get(id)
        return {
          value: id,
          label: row?.description || row?.file || id,
        }
      }),
    }
  }
  if (type === 'boolean' || type === 'bool') {
    return { ...base, type: 'boolean', secret: false }
  }
  if (type === 'number' || type === 'integer') {
    return { ...base, type: 'number', secret: false }
  }
  // Default and unknown types render as text.
  return { ...base, type: secret ? 'secret' : 'string' }
}

export function fieldsFromSchema(schema) {
  if (!Array.isArray(schema)) return []
  return schema.map(fieldFromSchema).filter(Boolean)
}

/** True when the public settings say this secret is stored (never the value). */
export function secretIsSet(settings, key) {
  if (!settings || typeof settings !== 'object') return false
  const flag = settings[key + 'Set']
  if (typeof flag === 'boolean') return flag
  return Boolean(String(settings[key] || '').length)
}

/** Local draft of settings values for editing (secrets start empty). */
export function draftFromPlugin(plugin) {
  const settings = plugin?.settings && typeof plugin.settings === 'object' ? plugin.settings : {}
  const draft = {}
  const secrets = {}
  for (const field of fieldsFromSchema(plugin?.schema)) {
    if (field.secret) {
      secrets[field.key] = secretIsSet(settings, field.key) ? 'set' : 'not set'
      draft[field.key] = ''
      continue
    }
    if (field.type === 'boolean') {
      draft[field.key] = Boolean(settings[field.key] ?? field.default)
      continue
    }
    if (field.type === 'number') {
      const raw = settings[field.key]
      draft[field.key] = raw == null || raw === '' ? field.default ?? '' : raw
      continue
    }
    draft[field.key] = settings[field.key] != null ? settings[field.key] : field.default ?? ''
  }
  return { enabled: Boolean(plugin?.enabled), draft, secrets }
}

/**
 * Body for PUT /api/plugins/<id>.
 * Secret keys are omitted unless the user typed a new value.
 */
export function pluginSaveBody({ enabled, draft, secrets, dirtySecrets }) {
  const body = {}
  if (typeof enabled === 'boolean') body.enabled = enabled
  if (draft && typeof draft === 'object') {
    const settings = {}
    for (const [key, value] of Object.entries(draft)) {
      if (secrets && key in secrets) {
        if (dirtySecrets && dirtySecrets[key] && String(value).length > 0) settings[key] = String(value)
        continue
      }
      settings[key] = value
    }
    if (Object.keys(settings).length) body.settings = settings
  }
  return body
}

export function readPluginSaveResult(status, body) {
  if (status === 409) {
    return {
      ok: false,
      conflict: true,
      error: (body && body.error) || 'Plugin settings changed. Refresh before saving.',
      body: body || null,
    }
  }
  if (status === 400 || status < 200 || status >= 300) {
    return {
      ok: false,
      conflict: false,
      error: (body && body.error) || 'Could not save plugin (' + status + ').',
      body: body || null,
    }
  }
  return { ok: true, conflict: false, error: null, body }
}

/** Printer exposes test-slip for the Settings panel button. */
export function pluginTestAction(plugin) {
  if (!plugin || plugin.id !== 'printer') return null
  return 'test-slip'
}

export function pluginIcon(plugin) {
  if (plugin?.id === 'printer') return '⎙'
  return '·'
}
