import { createContext, useContext, useEffect } from 'react'

// What the chat is looking at while a card is open (state-machine.md §5).
export const LookingContext = createContext(() => {})

export function useLookingAt(title) {
  const set = useContext(LookingContext)
  useEffect(() => {
    if (!title) return undefined
    set(title)
    return () => set(null)
  }, [title, set])
}
