import { describe, expect, it } from 'vitest'
import { chatDate, KINDS, matches, plateFor, provenance } from './kinds.js'

describe('recipe provenance', () => {
  it('names the category and where the card came from', () => {
    expect(provenance({ category: 'casseroles', source: "Quita's Recipe box", voice: 'grandma' })).toBe("Casseroles, from Quita's Recipe box")
  })
  it('skips placeholder sources and falls back to the voice', () => {
    expect(provenance({ category: 'breads', source: 'unknown', voice: 'grandma' })).toBe('Breads, from grandma')
    expect(provenance({ category: 'meats', source: 'zk-chat', voice: 'zk' })).toBe('Meats, from zk')
  })
  it('says only the category when nobody is known', () => {
    expect(provenance({ category: 'cakes', source: 'unknown', voice: 'unknown' })).toBe('Cakes')
    expect(provenance({ category: 'misc' })).toBe('Uncategorized')
  })
})

describe('plates', () => {
  it('uses the category plate, or the uncategorized rose', () => {
    expect(plateFor('fish-seafood')).toBe('/plates/fish-seafood.jpg')
    expect(plateFor('misc')).toBe('/plates/uncategorized.jpg')
  })
})

describe('chat dates', () => {
  it('uses created_at when it is real', () => {
    expect(chatDate({ created_at: '2026-10-18T12:00:00Z' })).not.toMatch(/Around/)
  })
  it('approximates imported chats from the earliest planned week', () => {
    const chat = { messages: [{ role: 'user', plan: { weekStart: '2026-09-12' } }, { role: 'user', plan: { weekStart: '2026-09-05' } }] }
    expect(chatDate(chat)).toMatch(/^Around the week of /)
    expect(chatDate(chat)).toMatch(/5/)
  })
  it('says undated when there is nothing to go on', () => {
    expect(chatDate({ messages: [{ role: 'user', content: 'hi' }] })).toBe('Undated')
  })
})

describe('items and search', () => {
  const body = {
    recipes: { recipes: [{ id: 'CBK-0044', title: 'Tamale Joe', category: 'casseroles', source: "Quita's Recipe box", ingredients: ['1 cup milk'] }] },
    state: { journal: [{ id: 'n1', text: 'Oven runs hot\nDrop 15°', type: 'kitchen', date: '2026-09-06' }], chats: [] },
  }
  it('maps recipes and notes onto one item shape', () => {
    const [r] = KINDS.recipes.items(body)
    expect(r).toMatchObject({ id: 'CBK-0044', title: 'Tamale Joe', line: "Casseroles, from Quita's Recipe box" })
    const [n] = KINDS.notes.items(body)
    expect(n.title).toBe('Oven runs hot')
    expect(n.line).toMatch(/^Kitchen, /)
  })
  it('matches every word, across id, title and ingredients', () => {
    const [r] = KINDS.recipes.items(body)
    expect(matches(r, 'tamale milk')).toBe(true)
    expect(matches(r, 'cbk-0044')).toBe(true)
    expect(matches(r, 'tamale fish')).toBe(false)
  })
})
