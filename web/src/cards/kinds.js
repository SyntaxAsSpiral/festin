// The three kinds the card machine runs (state-machine.md §4). Each kind maps its
// raw records onto one item shape: { id, title, line, tip, search, raw }.
import { liveState } from '../backend.js'

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

export function plateFor(category) {
  return '/plates/' + (CATEGORY_LABELS[category] ? category : 'uncategorized') + '.jpg'
}

// "Casseroles, from Quita's Recipe box" — category plus whoever the card came from.
export function provenance(recipe) {
  const label = CATEGORY_LABELS[recipe.category] || 'Uncategorized'
  const from = [recipe.source, recipe.voice].map((v) => String(v || '').trim()).find((v) => !PLACEHOLDER.test(v))
  return from ? label + ', from ' + from : label
}

function firstLine(text, max = 90) {
  const line = String(text || '').split('\n').map((l) => l.trim()).find(Boolean) || ''
  return line.length > max ? line.slice(0, max - 1).trimEnd() + '…' : line
}

export function dayOf(iso) {
  const d = iso ? new Date(iso + (iso.length === 10 ? 'T12:00:00' : '')) : null
  return d && !Number.isNaN(d.getTime()) ? d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : ''
}

// A chat's date. Festin chats carry created_at; chats imported from live have none,
// so they show the earliest week they planned against, as an approximation.
export function chatDate(chat) {
  const created = chat.created_at || chat.createdAt
  const approx = chat.date_approx ?? chat.dateApprox
  if (created && !approx) return dayOf(created)
  const weeks = (chat.messages || [])
    .map((m) => m.role === 'user' && m.plan && m.plan.weekStart)
    .filter(Boolean)
    .sort()
  const week = created || weeks[0]
  return week ? 'Around the week of ' + dayOf(String(week).slice(0, 10)) : 'Undated'
}

export const KINDS = {
  recipes: {
    id: 'recipes',
    noun: 'recipe',
    canCreate: true,
    searchLabel: 'Search recipes',
    empty: 'The recipe box is empty. Add a recipe, or ask Babette to.',
    items: (body) =>
      (body.recipes?.recipes || body.recipes || []).map((r) => ({
        id: r.id,
        title: r.title || r.id,
        line: provenance(r),
        tip: r.searchDescription || '',
        search: [r.id, r.title, r.category, r.source, r.voice, ...(r.ingredients || [])].join(' ').toLowerCase(),
        raw: r,
      })),
  },
  notes: {
    id: 'notes',
    noun: 'note',
    canCreate: true,
    searchLabel: 'Search notes',
    empty: 'No notes yet. Write one, or ask Babette to keep one.',
    items: (body) =>
      (body.state?.journal || []).map((n) => ({
        id: n.id,
        title: firstLine(n.text, 70),
        line: [n.type ? n.type[0].toUpperCase() + n.type.slice(1) : 'Note', dayOf(n.date)].filter(Boolean).join(', '),
        tip: '',
        search: [n.type, n.text].join(' ').toLowerCase(),
        raw: n,
      })),
  },
  chats: {
    id: 'chats',
    noun: 'chat',
    canCreate: false,
    searchLabel: 'Search chats',
    empty: 'No filed chats yet. +chat in the chat files the current one here.',
    items: (body) =>
      (body.state?.chats || []).map((c) => {
        const said = (c.messages || []).filter((m) => m.role === 'user' || m.role === 'assistant')
        return {
          id: c.id,
          title: firstLine(c.title || said[0]?.content || 'A chat', 80),
          line: chatDate(c),
          tip: firstLine(said.find((m) => m.role === 'assistant')?.content, 120),
          search: said.map((m) => m.content).join(' ').toLowerCase(),
          raw: c,
        }
      }),
  },
}

async function readJson(path) {
  const res = await fetch(path, { headers: { Accept: 'application/json' } })
  if (!res.ok) throw new Error(path + ' ' + res.status)
  return res.json()
}

async function pageAll(path, key, limit = 500) {
  const items = []
  let cursor = null
  while (items.length < limit) {
    const q = new URLSearchParams({ limit: String(Math.min(100, limit - items.length)) })
    if (cursor) q.set('cursor', cursor)
    const body = await readJson(path + '?' + q.toString())
    const page = body[key] || []
    items.push(...page)
    cursor = body.nextCursor
    if (!cursor || !page.length) break
  }
  return items
}

async function loadFestin(kind) {
  if (kind === 'recipes') {
    const recipes = await pageAll('/api/recipes', 'recipes')
    return KINDS.recipes.items({ recipes })
  }
  if (kind === 'notes') {
    const notes = await pageAll('/api/notes', 'notes')
    return KINDS.notes.items({
      state: {
        journal: notes.map((n) => ({
          id: n.id,
          text: n.text,
          type: n.type,
          date: n.date,
          color: n.color,
        })),
      },
    })
  }
  if (kind === 'chats') {
    const chats = await pageAll('/api/chats', 'chats')
    return chats.map((c) => ({
      id: c.id,
      title: firstLine(c.title || 'A chat', 80),
      line: chatDate({
        created_at: c.createdAt,
        date_approx: c.dateApprox,
      }),
      tip: firstLine(c.preview || '', 120),
      search: [c.title, c.preview].join(' ').toLowerCase(),
      raw: c,
    }))
  }
  throw new Error('unknown kind')
}

// Prefer the Festin list APIs; fall back to the live state body.
export function loadItems(kind) {
  return loadFestin(kind).catch(() => liveState().then((body) => KINDS[kind].items(body)))
}

export async function loadOne(kind, id) {
  if (kind === 'recipes') {
    const r = await readJson('/api/recipes/' + encodeURIComponent(id))
    return {
      id: r.id,
      title: r.title || r.id,
      line: provenance(r),
      tip: r.searchDescription || '',
      search: [r.id, r.title, r.category, r.source, r.voice, ...(r.ingredients || [])].join(' ').toLowerCase(),
      raw: r,
    }
  }
  if (kind === 'notes') {
    const n = await readJson('/api/notes/' + encodeURIComponent(id))
    return {
      id: n.id,
      title: firstLine(n.text, 70),
      line: [n.type ? n.type[0].toUpperCase() + n.type.slice(1) : 'Note', dayOf(n.date)].filter(Boolean).join(', '),
      tip: '',
      search: [n.type, n.text].join(' ').toLowerCase(),
      raw: n,
    }
  }
  if (kind === 'chats') {
    const c = await readJson('/api/chats/' + encodeURIComponent(id))
    const said = (c.messages || []).filter((m) => m.role === 'user' || m.role === 'assistant')
    return {
      id: c.id,
      title: firstLine(c.title || said[0]?.content || 'A chat', 80),
      line: chatDate(c),
      tip: firstLine(said.find((m) => m.role === 'assistant')?.content, 120),
      search: said.map((m) => m.content).join(' ').toLowerCase(),
      raw: c,
    }
  }
  throw new Error('unknown kind')
}

export function matches(item, query) {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  return words.every((w) => item.search.includes(w) || item.title.toLowerCase().includes(w))
}

// Writes arrive with the Festin API (festin-3d6.12.3). Until then the card says so
// rather than writing to the live kitchen.
export function notYet() {
  return Promise.reject(new Error('Saving arrives with the new kitchen backend. Nothing was changed.'))
}
