/** Kitchen Log entry labels (record type, then action) and timeline classes. */

export const RECIPE_EVENT_KINDS = new Set([
  'recipe_added',
  'recipe_edited',
  'recipe_cooked',
  'recipe_favourited',
  'recipe_planned',
  'photo_added',
])

const META = {
  recipe_added: { label: 'Recipe added', rowClass: 'tl-r', modClass: 'tl-a' },
  recipe_edited: { label: 'Recipe updated', rowClass: 'tl-r', modClass: 'tl-u' },
  recipe_cooked: { label: 'Cooked', rowClass: 'tl-cooked' },
  recipe_favourited: { label: 'Recipe favourited', rowClass: 'tl-fav' },
  recipe_planned: { label: 'Recipe planned', rowClass: 'tl-planned' },
  photo_added: { label: 'Recipe photo added', rowClass: 'tl-photo' },
  note_created: { label: 'Note created', rowClass: 'tl-c' },
  note_archived: { label: 'Note archived', rowClass: 'tl-archived' },
  chat: { label: 'Chat started', rowClass: 'tl-chat' },
}

export function entryMeta(kind) {
  return META[kind] || { label: 'Recipe updated', rowClass: 'tl-r', modClass: 'tl-u' }
}

/** Quiet ordinal for a cook past the first: "3rd time". Empty when ≤ 1. */
export function cookOrdinalDetail(ordinal) {
  const n = Number(ordinal)
  if (!Number.isFinite(n) || n < 2) return ''
  const mod100 = n % 100
  const mod10 = n % 10
  const suf =
    mod100 >= 11 && mod100 <= 13 ? 'th' : mod10 === 1 ? 'st' : mod10 === 2 ? 'nd' : mod10 === 3 ? 'rd' : 'th'
  return `${n}${suf} time`
}

export function conversationSummary(conversations) {
  const n = (conversations || []).length
  if (!n) return ''
  return `${n} conversation${n === 1 ? '' : 's'}`
}
