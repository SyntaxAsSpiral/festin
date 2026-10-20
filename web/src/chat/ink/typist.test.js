import { describe, expect, it } from 'vitest'
import { DEFAULT_TYPE_CPS, KEYS_PER_FRAME, MIN_SEEP_PACE, OVERLAP, STALL_RESET_MS } from './constants.js'
import { createTypist, keystrokeDelay, typistTick } from './typist.js'

describe('ghost typist', () => {
  it('spaces keystrokes around the writing speed with punctuation pauses', () => {
    const base = 1000 / 55
    // Fixed rng so the jitter is deterministic.
    const rng = () => 0.5
    const plain = keystrokeDelay('a', 55, rng)
    expect(plain).toBeCloseTo(base * (0.7 + 0.5 * 0.6), 5)
    expect(keystrokeDelay('.', 55, rng)).toBeCloseTo(plain + 220, 5)
    expect(keystrokeDelay(',', 55, rng)).toBeCloseTo(plain + 110, 5)
    expect(keystrokeDelay('!', 55, rng)).toBeCloseTo(plain + 220, 5)
    expect(keystrokeDelay(';', 55, rng)).toBeCloseTo(plain + 110, 5)
  })

  it('types only what has arrived, never rushing past the buffer', () => {
    const t = createTypist({ cps: 55, now: 0, rng: () => 0.5 })
    const a = typistTick(t, { received: 3, text: 'abc', now: 0 })
    expect(a.lit).toBe(1)
    expect(a.lit).toBeLessThanOrEqual(3)
    const b = typistTick(a, { received: 3, text: 'abc', now: a.nextKey })
    expect(b.lit).toBe(2)
  })

  it('caps keys per frame when several strokes are already due', () => {
    const t = createTypist({ cps: 55, now: 0, rng: () => 0 })
    // nextKey behind but inside the stall window: many strokes due, capped at 6.
    const behind = { ...t, lit: 0, nextKey: 0 }
    const text = 'x'.repeat(40)
    const out = typistTick(behind, { received: 40, text, now: 500 })
    expect(out.lit).toBe(KEYS_PER_FRAME)
  })

  it('after a long stall, resumes the rhythm instead of dumping the backlog', () => {
    const stalled = { ...createTypist({ cps: 55, now: 0, rng: () => 0 }), lit: 0, nextKey: 0 }
    const text = 'x'.repeat(40)
    const out = typistTick(stalled, { received: 40, text, now: STALL_RESET_MS + 50 })
    expect(out.lit).toBe(1)
    expect(out.nextKey).toBeGreaterThan(STALL_RESET_MS)
  })

  it('holds nextKey at now when caught up with the buffer', () => {
    const t = createTypist({ cps: 55, now: 100, rng: () => 0.5 })
    const out = typistTick({ ...t, lit: 2, nextKey: 50 }, { received: 2, text: 'ab', now: 200 })
    expect(out.lit).toBe(2)
    expect(out.nextKey).toBe(200)
  })

  it('reports the wet-band seep duration from the current pace', () => {
    const t = createTypist({ cps: DEFAULT_TYPE_CPS, now: 0 })
    expect(t.seepMs).toBe(Math.round((OVERLAP / Math.max(MIN_SEEP_PACE, DEFAULT_TYPE_CPS)) * 1000))
  })
})
