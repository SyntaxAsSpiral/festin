import { describe, expect, it } from 'vitest'
import { cropFor } from './scenes.js'

describe('banner crop from a zone', () => {
  it('covers the banner and keeps a wide zone in view', () => {
    const c = cropFor(580, 200, { x0: 0, y0: 0.4, x1: 1, y1: 1 })
    expect(c.width).toBeGreaterThanOrEqual(580)
    expect(c.height).toBeGreaterThanOrEqual(200)
    expect(c.top).toBeLessThanOrEqual(0)
    expect(-c.top + 200).toBeLessThanOrEqual(c.height + 0.001)
  })
  it('zooms in on a small zone, at most 1.6 times the cover scale', () => {
    const c = cropFor(580, 200, { x0: 0.45, y0: 0.45, x1: 0.55, y1: 0.55 })
    expect(c.width).toBeCloseTo(1280 * (580 / 1280) * 1.6, 3)
  })
})
