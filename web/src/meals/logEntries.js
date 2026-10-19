/** Kitchen Log entry labels (record type, then action) and timeline classes. */

export const RECIPE_EVENT_KINDS = new Set([
  'recipe_added',
  'recipe_edited',
  'recipe_cooked',
  'recipe_favourited',
  'photo_added',
])

const META = {
  recipe_added: { label: 'Recipe added', rowClass: 'tl-r', modClass: 'tl-a' },
  recipe_edited: { label: 'Recipe updated', rowClass: 'tl-r', modClass: 'tl-u' },
  recipe_cooked: { label: 'Recipe first cooked', rowClass: 'tl-cooked' },
  recipe_favourited: { label: 'Recipe favourited', rowClass: 'tl-fav' },
  photo_added: { label: 'Recipe photo added', rowClass: 'tl-photo' },
  note_created: { label: 'Note created', rowClass: 'tl-c' },
  note_archived: { label: 'Note archived', rowClass: 'tl-archived' },
  chat: { label: 'Chat started', rowClass: 'tl-chat' },
}

export function entryMeta(kind) {
  return META[kind] || { label: 'Recipe updated', rowClass: 'tl-r', modClass: 'tl-u' }
}

export function conversationSummary(conversations) {
  const n = (conversations || []).length
  if (!n) return ''
  return `${n} conversation${n === 1 ? '' : 's'}`
}
