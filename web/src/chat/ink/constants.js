// Babette's illustrated reply: Seep + Dip-pen dry. Tuned from ref/babettes-hand.html.

// The ghost typist still drives the seep study page. The live reveal does not.
export const DEFAULT_TYPE_CPS = 55

// Characters still seeping behind the pen on the study page.
export const OVERLAP = 20

// Household wet band: letters of seep, shared, 0 meaning plain text.
// 45 is 281 ms per letter at 160 characters per second, zk's study pick.
export const DEFAULT_WET_BAND = 45
export const WET_BAND_MAX = 60

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
// Dried ink; matches --bb-sepia in index.css, which settled replies use.
export const SEPIA = 'var(--bb-sepia, #7a5a3a)'

export function clampWetBand(value, fallback = DEFAULT_WET_BAND) {
  if (value == null || value === '') return fallback
  const n = typeof value === 'number' ? value : Number(String(value).trim())
  if (!Number.isInteger(n) || n < 0 || n > WET_BAND_MAX) return fallback
  return n
}

// Per-letter seep. Duration is the band divided by the pace, as on the study,
// but the pace counts as at least this. zk tuned the look at 160 letters a second
// (281 ms at a band of 45). A reply starts at the 60-a-second base pace, so its
// first letters would otherwise seep for a full second, a lone letter fading in
// patchily on an empty page, and read as a flicker.
export const MIN_SEEP_PACE = 160

export function seepMs(pace, band = DEFAULT_WET_BAND) {
  const b = clampWetBand(band)
  const p = Math.max(MIN_SEEP_PACE, Number(pace) || 1)
  return Math.round((b / p) * 1000)
}

// Band 0 is the ink layer's plain path, the same one reduced motion uses.
export function handIsPlain(band, reduced = false) {
  return Boolean(reduced) || clampWetBand(band) === 0
}
