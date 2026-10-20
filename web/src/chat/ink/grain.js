import { MASK_SIZE_EM } from './constants.js'

// How the seep is grained. 'letter' is each letter on its own noise pool (today).
// 'word' lights a word as one unit: its letters start together and read one
// continuous pool. A trial: pick with ?grain=word (or letter) once; it is kept.
export const GRAIN_KEY = 'festin.inkGrain'

export function readGrain() {
  try {
    const asked = new URLSearchParams(window.location.search).get('grain')
    if (asked === 'word' || asked === 'letter') localStorage.setItem(GRAIN_KEY, asked)
    return localStorage.getItem(GRAIN_KEY) === 'word' ? 'word' : 'letter'
  } catch {
    return 'letter'
  }
}

export function writeGrain(grain) {
  try {
    localStorage.setItem(GRAIN_KEY, grain === 'word' ? 'word' : 'letter')
  } catch {
    /* private mode */
  }
}

// Plan one frame's fresh letters as words. The browser decides where a mask's
// noise sits from its element's own box, so a word reads as one pool only if each
// letter's mask is shifted back by that letter's distance from its word's start.
//   startOf(i)     index of the first letter of i's word
//   offsetOf(i, s) how far letter i sits right of letter s, in px
//   baseOf(s)      the pool origin already given to that word, or null
// Letters of a word share one start moment (the first of them due this frame).
export function planWordSeep({ fresh, elapsed, startOf, offsetOf, baseOf, random = Math.random }) {
  const late = new Map()
  const bases = new Map()
  return fresh.map((index, j) => {
    const start = startOf(index)
    if (!late.has(start)) late.set(start, fresh.length > 1 ? (elapsed * (fresh.length - 1 - j)) / fresh.length : 0)
    let base = bases.get(start) || baseOf(start)
    if (!base) base = { x: +(random() * MASK_SIZE_EM).toFixed(2), y: +(random() * MASK_SIZE_EM).toFixed(2) }
    bases.set(start, base)
    return {
      index,
      start,
      base,
      lateMs: late.get(start),
      mx: `calc(${base.x}em - ${Math.round(offsetOf(index, start) * 10) / 10}px)`,
      my: `${base.y}em`,
    }
  })
}
