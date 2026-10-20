// Steady reveal. Text arrives in bursts; it is shown at an even pace. When a
// burst leaves more than LAG_MS of text waiting, the pace rises enough to clear
// it in LAG_MS. The rise is eased, so one frame does not jump to that pace
// and the letters do not land as a block. While that backlog is still waiting
// the pace holds; it does not step down mid-catch-up.

export const BASE_CPS = 60
// The fastest the reveal ever runs: zk finds the seep reads well up to about 400
// letters a second (2026-10-20: good at 400 with the band at max, gone at 1,000 and
// all at once). Faster streams wait their turn behind it. The seep takes
// band / pace, so keeping the pace at or under this also keeps it from collapsing
// to a flicker, which an uncapped pace did (30 ms at 1,000 a second).
export const MAX_CPS = 400
export const LAG_MS = 1200
// A frame longer than this (a background tab) counts as this long.
export const MAX_FRAME_MS = 100
// One frame moves the reveal at most this far, so a hitch lights a few letters
// (20 at the ceiling), not the whole backlog.
export const STEP_MS = 50
// Time constant for easing the pace toward the catch-up rate.
export const PACE_EASE_MS = 140

// shown is fractional; render Math.floor(shown) characters. cps is the pace
// carried from the previous frame, and the pace the seep is timed by: it never
// exceeds maxCps, so it is also the rate the letters really arrive at.
export function advance(shown, total, dtMs, cps = BASE_CPS, maxCps = MAX_CPS) {
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
  const pace = Math.min(maxCps, Math.max(BASE_CPS, carried + (aim - carried) * k))
  const next = Math.min(safeTotal, shown + (pace * Math.min(dt, STEP_MS)) / 1000)
  return { shown: next, cps: next >= safeTotal ? BASE_CPS : pace }
}
