import { describe, expect, it } from 'vitest'
import { followGrowth } from './Transcript.jsx'

describe('transcript follows growth', () => {
  it('scrolls when the page grew and its end is past the visible bottom', () => {
    expect(followGrowth(900, 700, 200)).toBe(true)
  })

  it('stays put when nothing grew', () => {
    expect(followGrowth(700, 700, 200)).toBe(false)
    expect(followGrowth(700.5, 700, 200)).toBe(false)
  })

  it('stays put when the end is already in view', () => {
    expect(followGrowth(900, 700, 0)).toBe(false)
    expect(followGrowth(900, 700, 4)).toBe(false)
  })
})
