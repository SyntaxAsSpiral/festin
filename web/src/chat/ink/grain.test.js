import { describe, expect, it, vi } from 'vitest'
import { GRAIN_KEY, planWordSeep, readGrain } from './grain.js'

const noBase = () => null

describe('word seep plan', () => {
  // "ab cd": letters 0,1 are one word, 3,4 another; 2 is the space.
  const startOf = (i) => (i < 2 ? 0 : 3)
  const offsetOf = (i, s) => (i - s) * 7
  const fresh = [0, 1, 3, 4]

  it('starts the letters of a word together and shifts each mask back by its offset', () => {
    const plan = planWordSeep({ fresh, elapsed: 16, startOf, offsetOf, baseOf: noBase, random: () => 0.5 })
    const [a, b, c, d] = plan
    expect(a.lateMs).toBe(b.lateMs)
    expect(c.lateMs).toBe(d.lateMs)
    expect(a.lateMs).not.toBe(c.lateMs)
    expect(a.mx).toBe('calc(1.2em - 0px)')
    expect(b.mx).toBe('calc(1.2em - 7px)')
    expect(d.mx).toBe('calc(1.2em - 7px)')
    expect(a.my).toBe(b.my)
  })

  it('keeps a word on its stored pool when its later letters arrive', () => {
    const plan = planWordSeep({ fresh: [1], elapsed: 16, startOf, offsetOf, baseOf: () => ({ x: 0.4, y: 1.1 }) })
    expect(plan[0].mx).toBe('calc(0.4em - 7px)')
    expect(plan[0].my).toBe('1.1em')
  })

  it('gives different words different pools', () => {
    let n = 0
    const plan = planWordSeep({ fresh, elapsed: 0, startOf, offsetOf, baseOf: noBase, random: () => (n++ % 4) / 4 })
    expect(plan[0].base).not.toEqual(plan[2].base)
  })
})

describe('grain choice', () => {
  it('is word without storage or a request', () => {
    expect(readGrain()).toBe('word')
  })

  it('keeps ?grain=letter once asked', () => {
    const store = {}
    vi.stubGlobal('window', { location: { search: '?grain=letter' } })
    vi.stubGlobal('localStorage', { getItem: (k) => store[k] ?? null, setItem: (k, v) => (store[k] = v) })
    expect(readGrain()).toBe('letter')
    expect(store[GRAIN_KEY]).toBe('letter')
    vi.stubGlobal('window', { location: { search: '' } })
    expect(readGrain()).toBe('letter')
    vi.unstubAllGlobals()
  })

  it('takes the request when the page loads, before a redirect drops it', async () => {
    const store = {}
    vi.stubGlobal('window', { location: { search: '?grain=letter' } })
    vi.stubGlobal('localStorage', { getItem: (k) => store[k] ?? null, setItem: (k, v) => (store[k] = v) })
    vi.resetModules()
    await import('./grain.js')
    expect(store[GRAIN_KEY]).toBe('letter')
    vi.unstubAllGlobals()
  })
})
