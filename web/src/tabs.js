export const TABS = [
  { id: 'meals', path: '/meals', label: 'Meals', key: 'M' },
  { id: 'recipes', path: '/recipes', label: 'Recipes', key: 'R' },
  { id: 'notes', path: '/notes', label: 'Notes', key: 'N' },
  { id: 'chats', path: '/chats', label: 'Chats', key: 'C' },
]

export function tabFromPath(pathname) {
  return TABS.find((tab) => pathname === tab.path || pathname.startsWith(tab.path + '/')) || null
}
