import { describe, expect, it } from 'vitest'
import {
  DEFAULT_TYPE_CPS,
  DEFAULT_WET_BAND,
  KEYS_PER_FRAME,
  LEVELS,
  MASK_SIZE_EM,
  OVERLAP,
  PAUSE_CLAUSE_MS,
  PAUSE_SENTENCE_MS,
  SEPIA,
  STALL_RESET_MS,
  WET,
  WET_BAND_MAX,
  clampWetBand,
  handIsPlain,
  seepMs,
} from './constants.js'

describe('ink constants', () => {
  it('keeps the Seep study defaults zk tuned', () => {
    expect(DEFAULT_TYPE_CPS).toBe(55)
    expect(OVERLAP).toBe(20)
    expect(LEVELS).toBe(40)
    expect(KEYS_PER_FRAME).toBe(6)
    expect(STALL_RESET_MS).toBe(1000)
    expect(PAUSE_SENTENCE_MS).toBe(220)
    expect(PAUSE_CLAUSE_MS).toBe(110)
    expect(MASK_SIZE_EM).toBe(2.4)
    expect(WET).toBe('#17130f')
    expect(SEPIA).toBe('var(--bb-sepia, #7a5a3a)')
  })

  it('shares one wet band, plain at zero', () => {
    expect(DEFAULT_WET_BAND).toBe(45)
    expect(WET_BAND_MAX).toBe(60)
    expect(clampWetBand(undefined)).toBe(45)
    expect(clampWetBand(0)).toBe(0)
    expect(clampWetBand(61)).toBe(45)
    expect(handIsPlain(0)).toBe(true)
    expect(handIsPlain(45)).toBe(false)
    expect(handIsPlain(45, true)).toBe(true)
  })

  it('derives seep length from pace and the wet band', () => {
    expect(seepMs(160, 45)).toBe(281)
    expect(seepMs(160, 0)).toBe(0)
    expect(seepMs(55, 20)).toBe(Math.round((20 / 55) * 1000))
    expect(seepMs(40, 20)).toBe(Math.round((20 / 40) * 1000))
  })
})
