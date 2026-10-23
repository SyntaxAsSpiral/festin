// Flick physics for the frieze: a drag's release velocity, then a spin that eases
// toward the drift speed (0 while held), so a hard flick runs on like a wheel of
// fortune and a gentle one drifts back into the column's own pace.

export const FLING_WINDOW_MS = 100
export const FLING_TAU_S = 1
export const FLING_MAX = 6000

// Velocity in px/s from drag samples [{ t, off }] (t in ms), over the last window
// before `now`. A finger that stopped before lifting has no velocity.
export function flingVelocity(samples, now, windowMs = FLING_WINDOW_MS) {
  const recent = samples.filter((s) => now - s.t <= windowMs)
  if (recent.length < 2) return 0
  const a = recent[0]
  const b = recent[recent.length - 1]
  const dt = (b.t - a.t) / 1000
  if (dt <= 0) return 0
  const v = (b.off - a.off) / dt
  return Math.max(-FLING_MAX, Math.min(FLING_MAX, v))
}

// One tick of the spin: v eases toward `target` with time constant tau.
export function spinStep(v, target, dt, tau = FLING_TAU_S) {
  return target + (v - target) * Math.exp(-dt / tau)
}
