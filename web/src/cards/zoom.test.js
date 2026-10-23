import { describe, expect, it } from 'vitest'
import { clampView, fitScale, fitView, isFitted, panBy, rotateView, zoomAt } from './zoom.js'

const img = { w: 4000, h: 3000 }
const box = { w: 800, h: 800 }

// Where an image point (from its centre, unscaled, unturned) lands on the stage.
function screen(v, u) {
  const a = (v.r * Math.PI) / 180
  const x = (u.x * Math.cos(a) - u.y * Math.sin(a)) * v.s + v.x
  const y = (u.x * Math.sin(a) + u.y * Math.cos(a)) * v.s + v.y
  return { x, y }
}

describe('scan viewer geometry', () => {
  it('fits the whole image, turned or not', () => {
    expect(fitScale(img, box, 0)).toBeCloseTo(0.2)
    expect(fitScale(img, { w: 800, h: 400 }, 90)).toBeCloseTo(400 / 4000)
  })

  it('zooming keeps the point under the pointer still', () => {
    const v = fitView(img, box)
    const u = { x: 1000, y: 500 }
    const p = screen(v, u)
    const z = zoomAt(v, 3, p.x, p.y, img, box)
    const q = screen(z, u)
    expect(q.x).toBeCloseTo(p.x)
    expect(q.y).toBeCloseTo(p.y)
  })

  it('zooming out stops at fitted, centred', () => {
    const z = zoomAt(fitView(img, box), 4, 200, 100, img, box)
    const out = zoomAt(z, 0.01, -300, 50, img, box)
    expect(isFitted(out, img, box)).toBe(true)
    expect(out.x).toBeCloseTo(0)
    expect(out.y).toBeCloseTo(0)
  })

  it('panning stops at the image edge', () => {
    const z = zoomAt(fitView(img, box), 5, 0, 0, img, box) // s = 1: 4000 x 3000
    const far = panBy(z, 99999, -99999, img, box)
    expect(far.x).toBeCloseTo((4000 - 800) / 2)
    expect(far.y).toBeCloseTo(-(3000 - 800) / 2)
  })

  it('a quarter turn keeps the stage centre on the same spot of the image', () => {
    const z = panBy(zoomAt(fitView(img, box), 5, 0, 0, img, box), 300, -200, img, box)
    const centreBefore = { x: -z.x / z.s, y: -z.y / z.s } // the image point at the stage centre, r = 0
    const t = rotateView(z, img, box)
    const at = screen(t, centreBefore)
    expect(t.r).toBe(90)
    expect(at.x).toBeCloseTo(0)
    expect(at.y).toBeCloseTo(0)
  })

  it('a fitted image stays fitted when turned, four turns come home', () => {
    let v = fitView(img, { w: 800, h: 400 })
    v = rotateView(v, img, { w: 800, h: 400 })
    expect(v.s).toBeCloseTo(0.1)
    for (let i = 0; i < 3; i++) v = rotateView(v, img, { w: 800, h: 400 })
    expect(v.r % 360).toBe(0)
    expect(v.s).toBeCloseTo(fitScale(img, { w: 800, h: 400 }, 0))
  })

  it('an axis smaller than the stage stays centred', () => {
    const tall = { w: 500, h: 4000 }
    const v = clampView({ s: 0.5, x: 300, y: 0, r: 0 }, tall, box)
    expect(v.x).toBeCloseTo(0)
  })
})
