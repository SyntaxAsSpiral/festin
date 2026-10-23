import { describe, expect, it } from 'vitest'
import { FLING_MAX, flingVelocity, spinStep } from './fling.js'

describe('flingVelocity', () => {
  it('reads px/s over the last window', () => {
    const s = [
      { t: 0, off: 0 },
      { t: 950, off: 10 },
      { t: 1000, off: 60 },
    ]
    expect(flingVelocity(s, 1000)).toBeCloseTo(1000)
  })

  it('is zero when the finger stopped before lifting', () => {
    const s = [
      { t: 0, off: 0 },
      { t: 50, off: 80 },
    ]
    expect(flingVelocity(s, 400)).toBe(0)
  })

  it('follows the flick direction and caps it', () => {
    const s = [
      { t: 0, off: 0 },
      { t: 10, off: -500 },
    ]
    expect(flingVelocity(s, 10)).toBe(-FLING_MAX)
  })
})

describe('spinStep', () => {
  it('decays a flick exponentially when held', () => {
    let v = 2000
    for (let i = 0; i < 60; i++) v = spinStep(v, 0, 1 / 60)
    expect(v).toBeCloseTo(2000 * Math.exp(-1), 0)
  })

  it('hands off to drift, easing in from either direction', () => {
    let up = 3000
    let down = -3000
    let still = 0
    for (let i = 0; i < 600; i++) {
      up = spinStep(up, 20, 1 / 60)
      down = spinStep(down, 20, 1 / 60)
      still = spinStep(still, 20, 1 / 60)
    }
    expect(up).toBeCloseTo(20, 0)
    expect(down).toBeCloseTo(20, 0)
    expect(spinStep(0, 20, 1 / 60)).toBeLessThan(1)
    expect(still).toBeCloseTo(20, 0)
  })

  it('a catch (v = 0, held) stays stopped', () => {
    expect(spinStep(0, 0, 0.5)).toBe(0)
  })
})
