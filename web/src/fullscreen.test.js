import { describe, expect, it } from 'vitest'
import { exitWasUser, setWantsFullscreen, wantsFullscreen } from './fullscreen.js'

function memory() {
  const m = new Map()
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, v), removeItem: (k) => m.delete(k) }
}

describe('the wish for full screen', () => {
  it('starts unwished, and holds what was set', () => {
    const s = memory()
    expect(wantsFullscreen(s)).toBe(false)
    setWantsFullscreen(true, s)
    expect(wantsFullscreen(s)).toBe(true)
    setWantsFullscreen(false, s)
    expect(wantsFullscreen(s)).toBe(false)
  })

  it('is unwished when storage throws', () => {
    const broken = { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') }, removeItem: () => {} }
    expect(wantsFullscreen(broken)).toBe(false)
    expect(() => setWantsFullscreen(true, broken)).not.toThrow()
  })
})

describe('who ended full screen', () => {
  it('a person, when the page never went hidden', () => {
    expect(exitWasUser({ hidden: false, hiddenAt: null, exitAt: 10_000 })).toBe(true)
  })
  it('a person, when the last hide was long before', () => {
    expect(exitWasUser({ hidden: false, hiddenAt: 1_000, exitAt: 10_000 })).toBe(true)
  })
  it('the browser, when the page is hidden now', () => {
    expect(exitWasUser({ hidden: true, hiddenAt: 10_000, exitAt: 10_050 })).toBe(false)
  })
  it('the browser, when the hide came just before the exit', () => {
    expect(exitWasUser({ hidden: false, hiddenAt: 9_500, exitAt: 10_000 })).toBe(false)
  })
  it('the browser, when the exit came just before the hide', () => {
    expect(exitWasUser({ hidden: false, hiddenAt: 10_600, exitAt: 10_000 })).toBe(false)
  })
})
