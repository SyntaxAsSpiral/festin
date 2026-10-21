import { describe, expect, it } from 'vitest'
import { hasSeenWelcome, markWelcomeSeen, showWelcome, WELCOME_EVENT } from './welcome.js'

function memory() {
  const m = new Map()
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, v) }
}

describe('first-run welcome', () => {
  it('is unseen on a fresh device, seen once marked', () => {
    const s = memory()
    expect(hasSeenWelcome(s)).toBe(false)
    markWelcomeSeen(s)
    expect(hasSeenWelcome(s)).toBe(true)
  })

  it('counts as unseen and does not throw when storage is blocked', () => {
    const blocked = { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') } }
    expect(hasSeenWelcome(blocked)).toBe(false)
    expect(() => markWelcomeSeen(blocked)).not.toThrow()
  })
})

describe('asking for the welcome again', () => {
  it('fires the event the dialog listens for', () => {
    const target = new EventTarget()
    let heard = 0
    target.addEventListener(WELCOME_EVENT, () => heard++)
    showWelcome(target)
    expect(heard).toBe(1)
  })
})
