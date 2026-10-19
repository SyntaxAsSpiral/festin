import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ARM_PX,
  THRESHOLD_PX,
  atTop,
  defaultReload,
  isBlockedRegion,
  isTypingTarget,
  pastThreshold,
  releaseAction,
  resistPull,
  shouldBeginPull,
} from './pullRefresh.js'

describe('pull-to-refresh threshold', () => {
  it('arms only after about 80 px of finger travel', () => {
    expect(THRESHOLD_PX).toBe(80)
    expect(pastThreshold(79)).toBe(false)
    expect(pastThreshold(80)).toBe(true)
    expect(pastThreshold(120)).toBe(true)
    expect(releaseAction(79)).toBe('cancel')
    expect(releaseAction(80)).toBe('reload')
    expect(releaseAction(200)).toBe('reload')
  })

  it('resists the visible pull so the line lags the finger', () => {
    expect(resistPull(0)).toBe(0)
    expect(resistPull(-10)).toBe(0)
    expect(resistPull(80)).toBeLessThan(80)
    expect(resistPull(80)).toBeGreaterThan(40)
    expect(resistPull(160)).toBeGreaterThan(resistPull(80))
    expect(resistPull(160)).toBeLessThan(160)
  })

  it('needs a short arm distance before tracking', () => {
    expect(ARM_PX).toBeGreaterThan(0)
    expect(ARM_PX).toBeLessThan(THRESHOLD_PX)
  })
})

describe('pull-to-refresh gates', () => {
  it('ignores mouse and desktop pointers', () => {
    expect(shouldBeginPull({ pointerType: 'mouse', narrow: true, target: null, root: null })).toBe(false)
    expect(shouldBeginPull({ pointerType: 'pen', narrow: true, target: null, root: null })).toBe(false)
    expect(shouldBeginPull({ pointerType: 'touch', narrow: false, target: null, root: null })).toBe(false)
    expect(shouldBeginPull({ pointerType: 'touch', narrow: true, target: null, root: null })).toBe(true)
  })

  it('skips a focused field and blocked regions; an unfocused field may pull', () => {
    const input = { closest: (sel) => (sel.includes('input') ? input : null) }
    const chat = { closest: (sel) => (String(sel).includes('surface') ? chat : null) }
    const card = { closest: (sel) => (String(sel).includes('card') ? card : null) }
    const ok = { closest: () => null }

    expect(isTypingTarget(input, input)).toBe(true)
    expect(isTypingTarget(input, null)).toBe(false)
    expect(isBlockedRegion(chat)).toBe(true)
    expect(isBlockedRegion(card)).toBe(true)
    expect(isBlockedRegion(ok)).toBe(false)

    expect(shouldBeginPull({ pointerType: 'touch', narrow: true, target: input, root: null, active: input })).toBe(false)
    expect(shouldBeginPull({ pointerType: 'touch', narrow: true, target: input, root: null, active: null })).toBe(true)
    expect(shouldBeginPull({ pointerType: 'touch', narrow: true, target: chat, root: null })).toBe(false)
    expect(shouldBeginPull({ pointerType: 'touch', narrow: true, target: card, root: null })).toBe(false)
    expect(shouldBeginPull({ pointerType: 'touch', narrow: true, target: ok, root: null })).toBe(true)
  })

  it('treats a scroller at scrollTop 0 as ready', () => {
    expect(atTop(null)).toBe(true)
    expect(atTop({ scrollTop: 0 })).toBe(true)
    expect(atTop({ scrollTop: 12 })).toBe(false)
  })
})

describe('pull-to-refresh reload hook', () => {
  afterEach(() => {
    if (typeof globalThis !== 'undefined') delete globalThis.__festinPullReload
  })

  it('prefers the test hook over a real reload', () => {
    const hook = vi.fn()
    globalThis.__festinPullReload = hook
    // Node has no window; the production path reads window when present.
    const prev = globalThis.window
    globalThis.window = globalThis
    defaultReload()
    expect(hook).toHaveBeenCalledOnce()
    if (prev === undefined) delete globalThis.window
    else globalThis.window = prev
  })
})
