import { BASE_CPS } from './reveal.js'

// The live reveal writes here. React state does not hear each letter: a dispatch
// from the animation frame re-renders the shell, and the meals page under the
// chat misses its frame.
export const revealPace = { shown: 0, cps: BASE_CPS }

let sink = null

export function resetRevealPace() {
  revealPace.shown = 0
  revealPace.cps = BASE_CPS
}

export function bindRevealSink(fn) {
  sink = fn
  return () => {
    if (sink === fn) sink = null
  }
}

export function pulseReveal() {
  sink?.()
}

export function visibleTail(text, shown) {
  const lines = String(text || '')
    .slice(0, Math.floor(shown) || 0)
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  return lines.length ? lines[lines.length - 1] : ''
}
