// Babette's illustrated reply: Seep + Dip-pen dry. Tuned from ref/babettes-hand.html.

export const DEFAULT_TYPE_CPS = 55
export const TYPE_CPS_MIN = 25
export const TYPE_CPS_MAX = 100

// Characters still seeping behind the front of the typist.
export const OVERLAP = 20

// Soft noise-mask levels for the seep keyframes.
export const LEVELS = 40
export const MASK_PX = 48
export const MASK_SIZE_EM = 2.4

export const KEYS_PER_FRAME = 6
export const STALL_RESET_MS = 1000
export const PAUSE_SENTENCE_MS = 220
export const PAUSE_CLAUSE_MS = 110

// Wet near-black on land; dries to sepia-brown (Dip pen), not plain ink.
export const WET = '#17130f'
export const SEPIA = '#7a5a3a'

export const SPEED_KEY = 'festin.writingSpeed'

export function seepMs(cps = DEFAULT_TYPE_CPS) {
  const pace = Math.max(1, Number(cps) || DEFAULT_TYPE_CPS)
  return Math.round((OVERLAP / pace) * 1000)
}

export function clampCps(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return DEFAULT_TYPE_CPS
  return Math.min(TYPE_CPS_MAX, Math.max(TYPE_CPS_MIN, Math.round(n)))
}
