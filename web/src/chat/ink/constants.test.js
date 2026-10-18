import { describe, expect, it } from 'vitest'
import {
  DEFAULT_TYPE_CPS,
  KEYS_PER_FRAME,
  LEVELS,
  MASK_SIZE_EM,
  OVERLAP,
  PAUSE_CLAUSE_MS,
  PAUSE_SENTENCE_MS,
  SEPIA,
  STALL_RESET_MS,
  TYPE_CPS_MAX,
  TYPE_CPS_MIN,
  WET,
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
    expect(SEPIA).toBe('#7a5a3a')
  })

  it('bounds the writing-speed slider', () => {
    expect(TYPE_CPS_MIN).toBe(25)
    expect(TYPE_CPS_MAX).toBe(100)
  })

  it('derives seep length from pace and the wet band', () => {
    expect(seepMs(55)).toBe(Math.round((20 / 55) * 1000))
    expect(seepMs(40)).toBe(Math.round((20 / 40) * 1000))
    expect(seepMs(100)).toBe(Math.round((20 / 100) * 1000))
  })
})
