import { useEffect, useState } from 'react'

const QUERY = '(prefers-reduced-motion: reduce)'
export const MOTION_KEY = 'festin.motion'

export function prefersReducedMotion() {
  const system = window.matchMedia(QUERY).matches
  let stored = null
  try {
    stored = localStorage.getItem(MOTION_KEY)
  } catch {
    stored = null
  }
  return system || stored === 'off'
}

export function useReducedMotion() {
  const [reduced, setReduced] = useState(prefersReducedMotion)
  useEffect(() => {
    const mq = window.matchMedia(QUERY)
    const sync = () => {
      const next = prefersReducedMotion()
      setReduced(next)
      document.documentElement.dataset.motion = next ? 'off' : 'on'
    }
    sync()
    mq.addEventListener('change', sync)
    window.addEventListener('storage', sync)
    window.addEventListener('festin-motion', sync)
    return () => {
      mq.removeEventListener('change', sync)
      window.removeEventListener('storage', sync)
      window.removeEventListener('festin-motion', sync)
    }
  }, [])
  return reduced
}
