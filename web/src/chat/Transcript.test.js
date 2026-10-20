import { describe, expect, it } from 'vitest'
import { followGrowth, traceStagger, TRACE_STAGGER_MS } from './Transcript.jsx'

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

  it('staggers steps that arrive together, by the gap', () => {
    const { delays, free } = traceStagger(0, 4, 1000, 0)
    expect(delays).toEqual([0, 1, 2, 3].map((n) => n * TRACE_STAGGER_MS))
    expect(free).toBe(1000 + 4 * TRACE_STAGGER_MS)
  })

  it('staggers steps that arrive in separate renders a few milliseconds apart', () => {
    // The first started at 1000, so the next, 4 ms later, waits out the gap.
    const second = traceStagger(1, 2, 1004, 1000 + TRACE_STAGGER_MS)
    expect(second.delays).toEqual([0, TRACE_STAGGER_MS - 4])
  })

  it('starts a lone step at once, and leaves earlier steps alone', () => {
    expect(traceStagger(3, 4, 5000, 1000).delays).toEqual([0, 0, 0, 0])
    expect(traceStagger(0, 0, 0, 0).delays).toEqual([])
  })
})
