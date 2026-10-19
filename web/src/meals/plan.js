// Slip week helpers and plan API mapping (state-machine.md §3).

export const DEFAULT_SLIP_TITLE = 'LE FESTIN'
export const SLIP_TITLE_MAX = 40
export const WEEK_BACK = 8
export const WEEK_AHEAD = 12

const WEEKDAY_NUM = { mon: 0, tue: 1, wed: 2, thu: 3, fri: 4, sat: 5, sun: 6 }
const WEEKDAY_LABEL = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const WEEKDAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

export function weekStartFor(day, startDay = 'sat') {
  const target = WEEKDAY_NUM[String(startDay || 'sat').slice(0, 3).toLowerCase()] ?? 5
  const d = asDate(day)
  // Align JS getDay (Sun=0) with Python weekday (Mon=0).
  const pyWeekday = (d.getDay() + 6) % 7
  const back = (pyWeekday - target + 7) % 7
  return addDays(d, -back)
}

export function isoDate(day) {
  const d = asDate(day)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const n = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${n}`
}

export function addDays(day, n) {
  const d = asDate(day)
  d.setDate(d.getDate() + n)
  return d
}

export function weekDates(weekStart) {
  const start = asDate(weekStart)
  return Array.from({ length: 7 }, (_, i) => isoDate(addDays(start, i)))
}

export function dayLabel(iso) {
  const d = asDate(iso)
  return WEEKDAY_LABEL[(d.getDay() + 6) % 7]
}

export function dayKey(iso) {
  return WEEKDAY_KEYS[(asDate(iso).getDay() + 6) % 7]
}

export function formatWeekLabel(iso, thisWeekIso) {
  const d = asDate(iso)
  const day = d.getDate()
  const month = d.toLocaleDateString('en-GB', { month: 'long' })
  const year = d.getFullYear()
  const y = year !== new Date().getFullYear() ? ` ${year}` : ''
  const base = `${day} ${month}${y}`
  return iso === thisWeekIso ? `${base} (this week)` : base
}

export function weekOptions(thisWeekIso, { back = WEEK_BACK, ahead = WEEK_AHEAD } = {}) {
  const start = asDate(thisWeekIso)
  const out = []
  for (let k = -back; k <= ahead; k++) {
    const iso = isoDate(addDays(start, k * 7))
    out.push({
      value: iso,
      label: `the week of ${formatWeekLabel(iso, thisWeekIso)}`,
    })
  }
  return out
}

export function formatDinnerHour(hhmm) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(hhmm || '17:30').trim())
  if (!m) return '5:30pm'
  let h = Number(m[1])
  const min = m[2]
  const ampm = h >= 12 ? 'pm' : 'am'
  h = h % 12 || 12
  return min === '00' ? `${h}${ampm}` : `${h}:${min}${ampm}`
}

// Accepts "12", "cbk 12", "CBK-0012", "CBK-12".
export function parseRecipeId(raw) {
  const text = String(raw || '').trim()
  if (!text) return null
  const compact = text.replace(/\s+/g, ' ')
  let m = /^CBK-(\d+)$/i.exec(compact)
  if (m) return 'CBK-' + m[1].padStart(4, '0')
  m = /^cbk[\s#-]*(\d+)$/i.exec(compact)
  if (m) return 'CBK-' + m[1].padStart(4, '0')
  m = /^(\d{1,6})$/.exec(compact)
  if (m) return 'CBK-' + m[1].padStart(4, '0')
  return null
}

export function displayRecipeId(id) {
  return id || ''
}

export function slipTitleOf(plan) {
  const raw = plan?.slipTitle ?? plan?.slipQuote ?? ''
  const text = String(raw).trim()
  return text || DEFAULT_SLIP_TITLE
}

// Map a GET /api/plans/:week body onto the editable slip draft.
export function planToDraft(plan) {
  const weekStart = plan.weekStart
  const days = (plan.days || []).slice(0, 7)
  while (days.length < 7) {
    const i = days.length
    days.push({
      day: dayKey(addDays(weekStart, i)),
      date: isoDate(addDays(weekStart, i)),
      recipe: null,
      title: '',
      ingredients: [],
      cooked: false,
    })
  }
  return {
    weekStart,
    slipTitle: slipTitleOf(plan),
    updatedAt: plan.updatedAt ?? null,
    days: days.map((slot, i) => ({
      day: slot.day || dayKey(slot.date || addDays(weekStart, i)),
      date: slot.date || isoDate(addDays(weekStart, i)),
      title: slot.title || '',
      recipe: slot.recipe || null,
      ingredients: Array.isArray(slot.ingredients) ? slot.ingredients : [],
      cooked: Boolean(slot.cooked),
    })),
  }
}

// Body for POST /api/plan (or PUT /api/plans/:week) with expected_updated_at.
export function draftToSaveBody(draft) {
  const title = String(draft.slipTitle || '').trim()
  return {
    weekStart: draft.weekStart,
    slipTitle: title === DEFAULT_SLIP_TITLE ? title : title,
    expected_updated_at: draft.updatedAt,
    days: draft.days.map((slot) => ({
      day: slot.day,
      date: slot.date,
      title: slot.title || '',
      recipe: slot.recipe || null,
      ingredients: slot.ingredients || [],
      cooked: Boolean(slot.cooked),
    })),
  }
}

export async function fetchSettings() {
  const res = await fetch('/api/settings', { headers: { Accept: 'application/json' } })
  if (!res.ok) throw new Error('settings ' + res.status)
  return res.json()
}

export async function fetchPlan(weekStart) {
  const res = await fetch('/api/plans/' + encodeURIComponent(weekStart), {
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) throw new Error('plan ' + res.status)
  return res.json()
}

export async function savePlan(draft) {
  const body = draftToSaveBody(draft)
  const res = await fetch('/api/plan', {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (res.status === 409) {
    const err = new Error('conflict')
    err.status = 409
    try {
      err.body = await res.json()
    } catch {
      err.body = null
    }
    throw err
  }
  if (!res.ok) {
    let message = 'save ' + res.status
    try {
      const data = await res.json()
      if (data?.error) message = data.error
    } catch {
      /* keep status message */
    }
    const err = new Error(message)
    err.status = res.status
    throw err
  }
  return res.json()
}

export async function fetchLogPage(before) {
  const q = new URLSearchParams()
  if (before) q.set('before', before)
  const res = await fetch('/api/log?' + q.toString(), { headers: { Accept: 'application/json' } })
  if (!res.ok) throw new Error('log ' + res.status)
  return res.json()
}

// A random handful of recipes, in one request (the frieze shows a fresh spread each visit).
export async function fetchRecipeSample(limit = 80) {
  const res = await fetch('/api/recipes?' + new URLSearchParams({ sample: '1', limit: String(limit) }), {
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) throw new Error('recipes ' + res.status)
  return (await res.json()).recipes || []
}

export async function fetchRecipes(limit = 100) {
  const items = []
  let cursor = null
  while (items.length < limit) {
    const q = new URLSearchParams({ limit: String(Math.min(100, limit - items.length)) })
    if (cursor) q.set('cursor', cursor)
    const res = await fetch('/api/recipes?' + q.toString(), { headers: { Accept: 'application/json' } })
    if (!res.ok) throw new Error('recipes ' + res.status)
    const body = await res.json()
    const page = body.recipes || []
    items.push(...page)
    cursor = body.nextCursor
    if (!cursor || !page.length) break
  }
  return items
}

export async function fetchPlugins() {
  try {
    const res = await fetch('/api/plugins', { headers: { Accept: 'application/json' } })
    if (res.status === 404) return null
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

export function printerIsOn(plugins) {
  if (!plugins) return false
  const list = Array.isArray(plugins) ? plugins : plugins.plugins || plugins.items
  if (Array.isArray(list)) {
    const printer = list.find((p) => (p.id || p.name || '').toLowerCase().includes('print'))
    if (!printer) return false
    return Boolean(printer.on ?? printer.enabled ?? printer.active)
  }
  const printer = plugins.printer || plugins.print || plugins['thermal-printer']
  if (!printer) return false
  return Boolean(printer.on ?? printer.enabled ?? printer.active)
}

function asDate(value) {
  if (value instanceof Date) return new Date(value.getFullYear(), value.getMonth(), value.getDate())
  const text = String(value).slice(0, 10)
  const [y, m, d] = text.split('-').map(Number)
  return new Date(y, m - 1, d)
}
