// Sort and filter for a collection list. Choices live on the device, same as layout.
import { CATEGORY_LABELS } from './kinds.js'

export const STORAGE_KEY = 'festin.sortfilter.'

export const SORT_IDS = ['name', 'id-newest', 'id-oldest', 'date-newest', 'date-oldest']

export const DEFAULT_CHOICE = Object.freeze({ sort: 'name', category: '', form: '', showArchived: false, favouritesOnly: false })

export const FORM_IDS = ['formule', 'praxis']

// Chats open on the most recent; recipes and notes on their names.
const DEFAULT_SORT = { chats: 'date-newest' }

export function defaultChoice(kind) {
  return { ...DEFAULT_CHOICE, sort: DEFAULT_SORT[kind] || 'name' }
}

export function isDefaultChoice(choice, kind = 'recipes') {
  if (!choice) return true
  const sortOk = !choice.sort || choice.sort === defaultChoice(kind).sort
  const catOk = !choice.category
  const formOk = !choice.form
  const archOk = !choice.showArchived
  const favOk = !choice.favouritesOnly
  return sortOk && catOk && formOk && archOk && favOk
}

export function cbkNumber(id) {
  const m = String(id || '').match(/(\d+)\s*$/)
  return m ? Number(m[1]) : 0
}

function byTitle(a, b) {
  return String(a.title || '').localeCompare(String(b.title || ''), undefined, { sensitivity: 'base' }) || String(a.id).localeCompare(String(b.id))
}

function byIdAsc(a, b) {
  return cbkNumber(a.id) - cbkNumber(b.id) || byTitle(a, b)
}

function byIdDesc(a, b) {
  return cbkNumber(b.id) - cbkNumber(a.id) || byTitle(a, b)
}

// A chat's last activity, else the day it began. Undated chats sort last either way.
function chatTime(item) {
  return String(item?.raw?.updatedAt || item?.raw?.createdAt || '')
}

function byDate(newest) {
  return (a, b) => {
    const x = chatTime(a)
    const y = chatTime(b)
    if (!x || !y) return (x ? 0 : 1) - (y ? 0 : 1) || byTitle(a, b)
    return (newest ? y.localeCompare(x) : x.localeCompare(y)) || byTitle(a, b)
  }
}

function isPinned(item) {
  return Boolean(item?.raw?.open)
}

export function filterByCategory(items, category) {
  if (!category) return items
  return items.filter((it) => it.raw && it.raw.category === category)
}

export function filterFavourites(items, favouritesOnly) {
  if (!favouritesOnly) return items
  return items.filter((it) => it.raw && it.raw.favourite)
}

export function filterByForm(items, form) {
  if (!form || !FORM_IDS.includes(form)) return items
  return items.filter((it) => {
    const kind = it.raw && it.raw.kind
    if (form === 'praxis') return kind === 'praxis'
    return kind !== 'praxis'
  })
}

export function sortItems(items, sort) {
  const out = items.slice()
  if (sort === 'id-newest') out.sort(byIdDesc)
  else if (sort === 'id-oldest') out.sort(byIdAsc)
  else if (sort === 'date-newest') out.sort(byDate(true))
  else if (sort === 'date-oldest') out.sort(byDate(false))
  else out.sort(byTitle)
  return out
}

/** Pinned notes first; within each group keep the sort already applied. */
export function pinThenArchived(items) {
  const pinned = []
  const archived = []
  for (const it of items) {
    if (isPinned(it)) pinned.push(it)
    else archived.push(it)
  }
  return pinned.concat(archived)
}

export function applySortFilter(items, choice, kind = 'recipes') {
  const sort = choice && SORT_IDS.includes(choice.sort) ? choice.sort : defaultChoice(kind).sort
  const category = choice && CATEGORY_LABELS[choice.category] ? choice.category : ''
  const showArchived = Boolean(choice && choice.showArchived)

  let list = items
  if (kind === 'chats') return sortItems(list, sort)
  if (kind === 'notes') {
    if (!showArchived) list = list.filter(isPinned)
    list = sortItems(list, sort)
    if (showArchived) list = pinThenArchived(list)
    return list
  }

  const favouritesOnly = Boolean(choice && choice.favouritesOnly)
  const form = choice && FORM_IDS.includes(choice.form) ? choice.form : ''
  return sortItems(filterFavourites(filterByForm(filterByCategory(list, category), form), favouritesOnly), sort)
}

export function summarizeChoice(choice, kind = 'recipes') {
  if (isDefaultChoice(choice, kind)) return ''
  const parts = []
  if (kind === 'chats') {
    if (choice.sort === 'date-oldest') return 'oldest first'
    if (choice.sort === 'name') return 'by name'
    return ''
  }
  if (kind === 'notes') {
    if (choice.sort === 'id-newest') parts.push('by ID, newest first')
    else if (choice.sort === 'id-oldest') parts.push('by ID, oldest first')
    if (choice.showArchived) parts.push('Show archived')
    return parts.join(', ')
  }
  if (choice.favouritesOnly) parts.push('Favourites only')
  if (choice.form === 'formule') parts.push('Formule')
  else if (choice.form === 'praxis') parts.push('Praxis')
  if (choice.category && CATEGORY_LABELS[choice.category]) parts.push(CATEGORY_LABELS[choice.category])
  if (choice.sort === 'id-newest') parts.push('by ID, newest first')
  else if (choice.sort === 'id-oldest') parts.push('by ID, oldest first')
  return parts.join(', ')
}

// Anything unknown falls back to its default, field by field.
function normalizeChoice(raw, kind) {
  if (!raw || typeof raw !== 'object') return defaultChoice(kind)
  return {
    sort: SORT_IDS.includes(raw.sort) ? raw.sort : defaultChoice(kind).sort,
    category: CATEGORY_LABELS[raw.category] ? raw.category : '',
    form: FORM_IDS.includes(raw.form) ? raw.form : '',
    showArchived: Boolean(raw.showArchived),
    favouritesOnly: Boolean(raw.favouritesOnly),
  }
}

export function readStoredChoice(kind) {
  try {
    const raw = localStorage.getItem(STORAGE_KEY + kind)
    if (!raw) return defaultChoice(kind)
    return normalizeChoice(JSON.parse(raw), kind)
  } catch {
    return defaultChoice(kind)
  }
}

export function writeStoredChoice(kind, choice) {
  try {
    localStorage.setItem(STORAGE_KEY + kind, JSON.stringify(normalizeChoice(choice, kind)))
  } catch {
    /* per-device nicety only */
  }
}
