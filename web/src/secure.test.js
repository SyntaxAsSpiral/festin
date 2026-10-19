import { describe, expect, it } from 'vitest'
import { newId } from './secure.js'

describe('ids on plain http', () => {
  it('makes a v4 uuid when randomUUID is withheld', () => {
    const original = crypto.randomUUID
    Object.defineProperty(crypto, 'randomUUID', { value: undefined, configurable: true })
    const id = newId()
    Object.defineProperty(crypto, 'randomUUID', { value: original, configurable: true })
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  })
  it('makes different ids', () => {
    expect(newId()).not.toBe(newId())
  })
})
