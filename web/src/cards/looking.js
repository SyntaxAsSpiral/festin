import { createContext, useContext, useEffect } from 'react'

// What the chat is looking at while a card is open (state-machine.md §5).
export const LookingContext = createContext(() => {})

// An open card reports its title (for the chat header) and a pointer (for the
// chat context sent with each message): { title, kind, id }.
export function useLookingAt(title, kind, id) {
  const set = useContext(LookingContext)
  useEffect(() => {
    if (!title) return undefined
    set({ title, kind, id })
    return () => set(null)
  }, [title, kind, id, set])
}
