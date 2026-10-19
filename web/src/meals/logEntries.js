/** Kitchen Log entry labels and timeline classes for each kind. */

export const RECIPE_EVENT_KINDS = new Set([
  'recipe_added',
  'recipe_edited',
  'recipe_cooked',
  'recipe_favourited',
  'photo_added',
])

const META = {
  recipe_added: { label: 'Added', rowClass: 'tl-r', modClass: 'tl-a' },
  recipe_edited: { label: 'Updated', rowClass: 'tl-r', modClass: 'tl-u' },
  recipe_cooked: { label: 'First cooked', rowClass: 'tl-cooked' },
  recipe_favourited: { label: 'Favourited', rowClass: 'tl-fav' },
  photo_added: { label: 'Photo added', rowClass: 'tl-photo' },
  note_created: { label: 'Note created', rowClass: 'tl-c' },
  note_archived: { label: 'Note archived', rowClass: 'tl-archived' },
  chat: { label: 'Chat', rowClass: 'tl-chat' },
}

export function entryMeta(kind) {
  return META[kind] || { label: 'Updated', rowClass: 'tl-r', modClass: 'tl-u' }
}

export function conversationSummary(conversations) {
  const n = (conversations || []).length
  if (!n) return ''
  return `${n} conversation${n === 1 ? '' : 's'}`
}
