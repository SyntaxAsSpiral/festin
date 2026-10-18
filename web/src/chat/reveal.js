// Steady reveal. Text arrives in bursts; it is shown at an even pace. When a
// burst leaves more than LAG_MS of text waiting, the pace rises enough to clear
// it in LAG_MS and holds there until caught up, so the reveal never slows mid-run.

export const BASE_CPS = 60
export const LAG_MS = 1200
// A frame longer than this (a background tab) counts as this long.
export const MAX_FRAME_MS = 100

// shown is fractional; render Math.floor(shown) characters. cps is the pace
// carried from the previous frame.
export function advance(shown, total, dtMs, cps = BASE_CPS) {
  if (shown >= total) return { shown: total, cps: BASE_CPS }
  const dt = Math.min(Math.max(dtMs, 0), MAX_FRAME_MS)
  const pace = Math.max(cps, BASE_CPS, (total - shown) / (LAG_MS / 1000))
  const next = Math.min(total, shown + (pace * dt) / 1000)
  return { shown: next, cps: next >= total ? BASE_CPS : pace }
}
