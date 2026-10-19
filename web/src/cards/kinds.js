// The three kinds the card machine runs (state-machine.md §4). Each kind maps a
// Festin record onto one item shape: { id, title, line, tip, search, raw }.
// Lists page through GET /api/<kind>. Writes send expected_updated_at and turn
// a 409 into one conflict the card can show, then reload.

export const CONFLICT_MESSAGE = 'Changed on another device. Reloaded.'

export class ConflictError extends Error {
  constructor() {
    super(CONFLICT_MESSAGE)
    this.name = 'ConflictError'
    this.status = 409
  }
}

export const CATEGORY_LABELS = {
  breads: 'Breads',
  cakes: 'Cakes',
  'pies-tarts': 'Pies & Tarts',
  cookies: 'Cookies & Bars',
  sweets: 'Sweets',
  casseroles: 'Casseroles',
  chicken: 'Chicken',
  meats: 'Meats',
  'fish-seafood': 'Fish & Seafood',
  pasta: 'Pasta & Rice',
  'soups-stews': 'Soups & Stews',
  'salads-sides': 'Salads & Sides',
  'pantry-party': 'Pantry & Party',
  'sauces-dressings': 'Sauces & Dressings',
  drinks: 'Drinks',
  'pickles-preserves': 'Pickles & Preserves',
  'eggs-breakfast': 'Eggs & Breakfast',
  seasonings: 'Seasonings',
  'snacks-sandwiches': 'Snacks & Sandwiches',
}

const PLACEHOLDER = /^(unknown|zk-chat|)$/i
const WEEKDAYS = { mon: 0, tue: 1, wed: 2, thu: 3, fri: 4, sat: 5, sun: 6 }
const LIST_KEY = { recipes: 'recipes', notes: 'notes', chats: 'chats' }

export function plateFor(category) {
  return '/plates/' + (CATEGORY_LABELS[category] ? category : 'uncategorized') + '.jpg'
}

// "Casseroles, from Quita's Recipe box" — category plus whoever the card came from.
export function provenance(recipe) {
  const label = CATEGORY_LABELS[recipe.category] || 'Uncategorized'
  const from = [recipe.source, recipe.voice].map((v) => String(v || '').trim()).find((v) => !PLACEHOLDER.test(v))
  return from ? label + ', from ' + from : label
}

function lines(text) {
  return String(text || '').split('\n').map((l) => l.trim()).filter(Boolean)
}

function firstLine(text, max = 90) {
  const line = lines(text)[0] || ''
  return line.length > max ? line.slice(0, max - 1).trimEnd() + '…' : line
}

export function dayOf(iso) {
  const d = iso ? new Date(iso + (iso.length === 10 ? 'T12:00:00' : '')) : null
  return d && !Number.isNaN(d.getTime()) ? d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : ''
}

// A chat's date. A real createdAt is the day. Imported chats are an approximation
// (dateApprox, or the older created_at plus the earliest planned week).
export function chatDate(chat) {
  const created = chat.createdAt || chat.created_at || ''
  const approx = Boolean(chat.dateApprox || chat.date_approx)
  if (created && !approx) return dayOf(created)
  if (created && approx) return 'Around the week of ' + dayOf(String(created).slice(0, 10))
  const weeks = (chat.messages || [])
    .map((m) => m.role === 'user' && m.plan && m.plan.weekStart)
    .filter(Boolean)
    .sort()
  return weeks[0] ? 'Around the week of ' + dayOf(weeks[0].slice(0, 10)) : 'Undated'
}

export function recipeItem(r) {
  return {
    id: r.id,
    title: r.title || r.id,
    line: provenance(r),
    tip: r.searchDescription || '',
    search: [r.id, r.title, r.category, r.source, r.voice, r.searchDescription, r.notes, ...(r.ingredients || [])].join(' ').toLowerCase(),
    card: null,
    raw: r,
  }
}

export function noteItem(n) {
  return {
    id: n.id,
    title: firstLine(n.text, 70) || 'A note',
    line: [n.type ? n.type[0].toUpperCase() + n.type.slice(1) : 'Note', dayOf(n.date)].filter(Boolean).join(', '),
    tip: '',
    search: [n.type, n.text].join(' ').toLowerCase(),
    // Cards show the whole note: its first line as the title, the rest below.
    card: { title: lines(n.text)[0] || 'A note', tip: lines(n.text).slice(1).join('\n') },
    raw: n,
  }
}

// Cards show the first lines whole. Live cut stored chat titles short, so when the
// title is just the start of the first message, the card uses the whole line and
// doesn't repeat it underneath.
function chatCard(c, said, tipSrc) {
  const stored = lines(c.title)[0] || ''
  const opening = lines(c.preview || said[0]?.content)[0] || ''
  const title = opening && opening.startsWith(stored.replace(/[\s\\]+$/, '')) ? opening : stored || opening || 'A chat'
  const tip = lines(tipSrc)[0] || ''
  return { title, tip: tip === title || title.startsWith(tip) ? '' : tip }
}

export function chatItem(c) {
  const said = (c.messages || []).filter((m) => m.role === 'user' || m.role === 'assistant')
  const title = firstLine(c.title || said[0]?.content || 'A chat', 80)
  const assistant = said.find((m) => m.role === 'assistant')?.content
  const tipSrc = assistant || (c.preview && c.preview !== c.title ? c.preview : '')
  return {
    id: c.id,
    title,
    line: chatDate(c),
    tip: firstLine(tipSrc, 120),
    search: [c.title, c.preview, ...said.map((m) => m.content)].join(' ').toLowerCase(),
    card: chatCard(c, said, tipSrc),
    raw: c,
  }
}

const TO_ITEM = { recipes: recipeItem, notes: noteItem, chats: chatItem }

export function toItem(kind, row) {
  return TO_ITEM[kind](row)
}

export const KINDS = {
  recipes: {
    id: 'recipes',
    noun: 'recipe',
    canCreate: true,
    searchLabel: 'Search recipes',
    empty: 'The recipe box is empty. Add a recipe, or ask Babette to.',
    items: (rows) => rows.map(recipeItem),
  },
  notes: {
    id: 'notes',
    noun: 'note',
    canCreate: true,
    searchLabel: 'Search notes',
    empty: 'No notes yet. Write one, or ask Babette to keep one.',
    items: (rows) => rows.map(noteItem),
  },
  chats: {
    id: 'chats',
    noun: 'chat',
    canCreate: false,
    searchLabel: 'Search chats',
    empty: 'No filed chats yet. +chat in the chat files the current one here.',
    items: (rows) => rows.map(chatItem),
  },
}

async function send(method, path, body, { conflict = true } = {}) {
  const res = await fetch(path, {
    method,
    headers: {
      Accept: 'application/json',
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  let data = null
  try {
    data = await res.json()
  } catch {
    data = null
  }
  if (res.status === 409) {
    if (conflict) throw new ConflictError()
    throw new Error((data && data.error) || CONFLICT_MESSAGE)
  }
  if (!res.ok) throw new Error((data && data.error) || 'The kitchen did not save that.')
  return data
}

async function pageAll(kind, query) {
  const key = LIST_KEY[kind]
  const rows = []
  const seen = new Set()
  let cursor = ''
  for (;;) {
    const params = new URLSearchParams({ limit: '100' })
    if (query) params.set('q', query)
    if (cursor) params.set('cursor', cursor)
    const page = await send('GET', '/api/' + kind + '?' + params)
    rows.push(...(page[key] || []))
    const next = page.nextCursor || ''
    if (!next || seen.has(next)) break
    seen.add(next)
    cursor = next
  }
  return rows
}

// Recipes and notes come back whole enough to search here. Chats are summaries,
// so a typed query uses the server's q=, which reads the transcript.
export function loadItems(kind, query = '') {
  const q = kind === 'chats' ? query.trim() : ''
  return pageAll(kind, q).then((rows) => KINDS[kind].items(rows))
}

export function loadItem(kind, id) {
  return send('GET', '/api/' + kind + '/' + encodeURIComponent(id)).then((row) => toItem(kind, row))
}

export function matches(item, query) {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  return words.every((w) => item.search.includes(w) || item.title.toLowerCase().includes(w))
}

export function recipeFields(draft) {
  return {
    title: String(draft.title || '').trim(),
    category: draft.category || '',
    ingredients: String(draft.ingredients || '')
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean),
    method: draft.method || '',
    notes: draft.notes || '',
  }
}

export function saveRecipe(recipe, draft) {
  const fields = recipeFields(draft)
  if (!recipe) return send('POST', '/api/recipes', fields)
  return send('POST', '/api/recipes/' + encodeURIComponent(recipe.id), {
    expected_updated_at: recipe.updatedAt,
    ...fields,
  })
}

export function saveNote(note, fields) {
  if (!note) {
    return send('POST', '/api/notes', {
      text: fields.text,
      type: 'note',
      color: fields.color || 'none',
      // New notes from the UI are pinned so they appear in the default list.
      open: true,
    })
  }
  const body = { expected_updated_at: note.updatedAt }
  if (fields.text !== undefined) body.text = fields.text
  if (fields.color !== undefined) body.color = fields.color
  return send('POST', '/api/notes/' + encodeURIComponent(note.id), body)
}

export function toggleNote(note) {
  return send('POST', '/api/notes/' + encodeURIComponent(note.id) + '/toggle', {
    expected_updated_at: note.updatedAt,
  })
}

export function removeItem(kind, raw) {
  return send('DELETE', '/api/' + kind + '/' + encodeURIComponent(raw.id), {
    expected_updated_at: raw.updatedAt,
  })
}

// Calendar date in the household zone. en-CA formats as YYYY-MM-DD.
export function householdDate(timeZone, now = new Date()) {
  const zone = timeZone && timeZone !== 'auto' ? timeZone : undefined
  try {
    return new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(now)
  } catch {
    return new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(now)
  }
}

// Week start on or before `iso`, using the same weekday numbers as the kitchen.
export function weekStartOn(iso, startDay) {
  const [y, m, d] = iso.split('-').map(Number)
  const date = new Date(Date.UTC(y, m - 1, d))
  const weekday = (date.getUTCDay() + 6) % 7
  const target = WEEKDAYS[startDay] ?? WEEKDAYS.sat
  date.setUTCDate(date.getUTCDate() - ((weekday - target + 7) % 7))
  return date.toISOString().slice(0, 10)
}

// Marks tonight's plan night cooked, and names this recipe on it.
export async function cookTonight(recipe) {
  const settings = await send('GET', '/api/settings')
  const today = householdDate(settings.weather && settings.weather.timezone)
  const start = weekStartOn(today, settings.weekStart)
  const plan = await send('GET', '/api/plans/' + start)
  let found = false
  const days = (plan.days || []).map((day) => {
    if (day.date !== today) return day
    found = true
    return { ...day, recipe: recipe.id, title: day.title || recipe.title || '', cooked: true }
  })
  if (!found) throw new Error("Tonight is not on this week's plan.")
  return send('POST', '/api/plans/' + encodeURIComponent(start), {
    weekStart: start,
    slipTitle: plan.slipTitle || '',
    notes: plan.notes || '',
    ...(plan.plates ? { plates: plan.plates } : {}),
    expected_updated_at: plan.updatedAt,
    days,
  })
}

// Points this device's session at the chat. A mid-turn 409 stays the server's words.
export function pointSessionAt(chatId) {
  return send('PUT', '/api/session', { chat_id: chatId }, { conflict: false })
}
