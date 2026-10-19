// Sort and filter for a collection list. Choices live on the device, same as layout.
import { CATEGORY_LABELS } from './kinds.js'

export const STORAGE_KEY = 'festin.sortfilter.'

export const SORT_IDS = ['name', 'id-newest', 'id-oldest']

export const DEFAULT_CHOICE = Object.freeze({ sort: 'name', category: '', showArchived: false })

export function isDefaultChoice(choice) {
  if (!choice) return true
  const sortOk = !choice.sort || choice.sort === 'name'
  const catOk = !choice.category
  const archOk = !choice.showArchived
  return sortOk && catOk && archOk
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

function isPinned(item) {
  return Boolean(item?.raw?.open)
}

export function filterByCategory(items, category) {
  if (!category) return items
  return items.filter((it) => it.raw && it.raw.category === category)
}

export function sortItems(items, sort) {
  const out = items.slice()
  if (sort === 'id-newest') out.sort(byIdDesc)
  else if (sort === 'id-oldest') out.sort(byIdAsc)
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
  const sort = choice && SORT_IDS.includes(choice.sort) ? choice.sort : 'name'
  const category = choice && CATEGORY_LABELS[choice.category] ? choice.category : ''
  const showArchived = Boolean(choice && choice.showArchived)

  let list = items
  if (kind === 'notes') {
    if (!showArchived) list = list.filter(isPinned)
    list = sortItems(list, sort)
    if (showArchived) list = pinThenArchived(list)
    return list
  }

  return sortItems(filterByCategory(list, category), sort)
}

export function summarizeChoice(choice, kind = 'recipes') {
  if (isDefaultChoice(choice)) return ''
  const parts = []
  if (kind === 'notes') {
    if (choice.sort === 'id-newest') parts.push('by ID, newest first')
    else if (choice.sort === 'id-oldest') parts.push('by ID, oldest first')
    if (choice.showArchived) parts.push('Show archived')
    return parts.join(', ')
  }
  if (choice.category && CATEGORY_LABELS[choice.category]) parts.push(CATEGORY_LABELS[choice.category])
  if (choice.sort === 'id-newest') parts.push('by ID, newest first')
  else if (choice.sort === 'id-oldest') parts.push('by ID, oldest first')
  return parts.join(', ')
}

function normalizeChoice(raw) {
  if (!raw || typeof raw !== 'object') return { ...DEFAULT_CHOICE }
  const sort = SORT_IDS.includes(raw.sort) ? raw.sort : 'name'
  const category = CATEGORY_LABELS[raw.category] ? raw.category : ''
  const showArchived = Boolean(raw.showArchived)
  if (!SORT_IDS.includes(raw.sort) && raw.category && !CATEGORY_LABELS[raw.category] && !raw.showArchived) {
    return { ...DEFAULT_CHOICE }
  }
  if (!SORT_IDS.includes(raw.sort) && !raw.category && !raw.showArchived) return { ...DEFAULT_CHOICE }
  if (!SORT_IDS.includes(raw.sort) && (category || showArchived)) {
    return { sort: 'name', category, showArchived }
  }
  return { sort, category, showArchived }
}

export function readStoredChoice(kind) {
  try {
    const raw = localStorage.getItem(STORAGE_KEY + kind)
    if (!raw) return { ...DEFAULT_CHOICE }
    return normalizeChoice(JSON.parse(raw))
  } catch {
    return { ...DEFAULT_CHOICE }
  }
}

export function writeStoredChoice(kind, choice) {
  try {
    localStorage.setItem(STORAGE_KEY + kind, JSON.stringify(normalizeChoice(choice)))
  } catch {
    /* per-device nicety only */
  }
}
