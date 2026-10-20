// Steady reveal. Text arrives in bursts; it is shown at an even pace. When a
// burst leaves more than LAG_MS of text waiting, the pace rises enough to clear
// it in LAG_MS. The rise is eased, so one frame does not jump to that pace
// and the letters do not land as a block. While that backlog is still waiting
// the pace holds; it does not step down mid-catch-up.

export const BASE_CPS = 60
export const LAG_MS = 1200
// A frame longer than this (a background tab) counts as this long.
export const MAX_FRAME_MS = 100
// A hitch must not light a block. The layer spreads a frame's letters across
// that frame; this is how many it is allowed to start.
export const MAX_LETTERS_PER_FRAME = 4
// Time constant for easing the pace toward the catch-up rate.
export const PACE_EASE_MS = 140

// shown is fractional; render Math.floor(shown) characters. cps is the pace
// carried from the previous frame.
// maxLetters is the per-frame limit; the study page sweeps it.
export function advance(shown, total, dtMs, cps = BASE_CPS, maxLetters = MAX_LETTERS_PER_FRAME) {
  const safeTotal = Math.max(0, Number(total) || 0)
  if (shown >= safeTotal) return { shown: safeTotal, cps: BASE_CPS }
  const dt = Math.min(Math.max(Number(dtMs) || 0, 0), MAX_FRAME_MS)
  const carried = Number.isFinite(cps) && cps > 0 ? cps : BASE_CPS
  const backlog = safeTotal - shown
  const lagSec = LAG_MS / 1000
  const target = Math.max(BASE_CPS, backlog / lagSec)
  // More than a lag-window still waiting: aim at the catch-up rate, but never
  // below the pace already reached. A smaller backlog eases back toward base.
  const aim = backlog > BASE_CPS * lagSec ? Math.max(target, carried) : target
  const k = dt === 0 ? 0 : 1 - Math.exp(-dt / PACE_EASE_MS)
  const pace = Math.max(BASE_CPS, carried + (aim - carried) * k)
  const stepped = shown + (pace * dt) / 1000
  const next = Math.min(safeTotal, stepped, shown + maxLetters)
  return { shown: next, cps: next >= safeTotal ? BASE_CPS : pace }
}
