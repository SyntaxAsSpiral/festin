import {
  DEFAULT_TYPE_CPS,
  KEYS_PER_FRAME,
  OVERLAP,
  PAUSE_CLAUSE_MS,
  PAUSE_SENTENCE_MS,
  STALL_RESET_MS,
  seepMs,
} from './constants.js'

export function keystrokeDelay(ch, cps = DEFAULT_TYPE_CPS, rng = Math.random) {
  const base = 1000 / Math.max(1, cps)
  const jitter = base * (0.7 + rng() * 0.6)
  if (/[.!?]/.test(ch)) return jitter + PAUSE_SENTENCE_MS
  if (/[,;:]/.test(ch)) return jitter + PAUSE_CLAUSE_MS
  return jitter
}

export function createTypist({ cps = DEFAULT_TYPE_CPS, now = 0, rng = Math.random } = {}) {
  return {
    lit: 0,
    nextKey: now,
    cps,
    seepMs: seepMs(cps, OVERLAP),
    rng,
  }
}

// Advance the ghost typist one animation frame. Types up to KEYS_PER_FRAME
// characters that are due, never past what the stream has received. After a
// stall longer than STALL_RESET_MS, the rhythm resumes from now.
export function typistTick(state, { received, text, now }) {
  const cps = state.cps || DEFAULT_TYPE_CPS
  const rng = state.rng || Math.random
  let { lit, nextKey } = state
  const total = Math.min(Math.max(0, received | 0), String(text || '').length)

  if (now - nextKey > STALL_RESET_MS) nextKey = now

  let keys = 0
  while (lit < total && now >= nextKey && keys++ < KEYS_PER_FRAME) {
    const ch = text[lit]
    nextKey += keystrokeDelay(ch, cps, rng)
    lit++
  }
  if (lit >= total) nextKey = Math.max(nextKey, now)

  return {
    ...state,
    lit,
    nextKey,
    cps,
    seepMs: seepMs(cps, OVERLAP),
    rng,
  }
}
