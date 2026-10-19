import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  CONFLICT_MESSAGE,
  ConflictError,
  chatDate,
  chatItem,
  KINDS,
  loadItems,
  matches,
  noteItem,
  plateFor,
  provenance,
  recipeItem,
  saveRecipe,
  weekStartOn,
} from './kinds.js'

describe('recipe provenance', () => {
  it('names the category and where the card came from', () => {
    expect(provenance({ category: 'casseroles', source: 'Family Circle', voice: "Quita's recipe box" })).toBe("Casseroles, from Quita's recipe box")
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
  it('treats a Festin dateApprox stamp as the week it was planned', () => {
    expect(chatDate({ createdAt: '2026-09-05', dateApprox: true })).toMatch(/^Around the week of /)
    expect(chatDate({ createdAt: '2026-09-05', dateApprox: true })).toMatch(/5/)
  })
  it('approximates older imported chats from the earliest planned week', () => {
    const chat = { messages: [{ role: 'user', plan: { weekStart: '2026-09-12' } }, { role: 'user', plan: { weekStart: '2026-09-05' } }] }
    expect(chatDate(chat)).toMatch(/^Around the week of /)
    expect(chatDate(chat)).toMatch(/5/)
  })
  it('says undated when there is nothing to go on', () => {
    expect(chatDate({ messages: [{ role: 'user', content: 'hi' }] })).toBe('Undated')
  })
})

describe('the week a cooked night lands on', () => {
  it('walks back to the configured start day', () => {
    expect(weekStartOn('2026-10-18', 'sat')).toBe('2026-10-17')
    expect(weekStartOn('2026-10-17', 'sat')).toBe('2026-10-17')
    expect(weekStartOn('2026-10-18', 'sun')).toBe('2026-10-18')
  })
})

describe('items and search', () => {
  const recipe = {
    id: 'CBK-0044',
    title: 'Tamale Joe',
    category: 'casseroles',
    voice: "Quita's recipe box",
    ingredients: ['1 cup milk'],
    searchDescription: 'A baked tamale',
    updatedAt: '2026-10-18T00:00:00.000000Z',
  }
  const note = { id: 'n1', text: 'Oven runs hot\nDrop 15°', type: 'kitchen', date: '2026-09-06', color: 'peach', updatedAt: 't' }
  const chat = { id: 'c1', title: 'Sunday soup', createdAt: '2026-10-01T12:00:00Z', dateApprox: false, preview: 'What should we eat', updatedAt: 't' }

  it('maps a Festin recipe, note and chat onto one item shape', () => {
    const r = recipeItem(recipe)
    expect(r).toMatchObject({ id: 'CBK-0044', title: 'Tamale Joe', line: "Casseroles, from Quita's recipe box", tip: 'A baked tamale' })
    expect(r.raw).toBe(recipe)
    const n = noteItem(note)
    expect(n.title).toBe('Oven runs hot')
    expect(n.line).toMatch(/^Kitchen, /)
    const c = chatItem(chat)
    expect(c.title).toBe('Sunday soup')
    expect(c.line).not.toMatch(/Around/)
    expect(KINDS.recipes.items([recipe])[0].id).toBe('CBK-0044')
    expect(KINDS.notes.items([note])[0].title).toBe('Oven runs hot')
  })
  it('matches every word, across id, title and ingredients', () => {
    const r = recipeItem(recipe)
    expect(matches(r, 'tamale milk')).toBe(true)
    expect(matches(r, 'cbk-0044')).toBe(true)
    expect(matches(r, 'tamale fish')).toBe(false)
  })
})

function jsonResponse(status, body) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: async () => body,
  }
}

describe('list paging and the 409 path', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('follows nextCursor until the list is whole', async () => {
    const fetch = vi.fn(async (url) => {
      if (String(url).includes('cursor=')) {
        return jsonResponse(200, {
          recipes: [{ id: 'CBK-0002', title: 'Bread', category: 'breads', ingredients: ['flour'] }],
          nextCursor: null,
        })
      }
      return jsonResponse(200, {
        recipes: [{ id: 'CBK-0001', title: 'Cake', category: 'cakes', voice: "Quita's recipe box", ingredients: ['1/2 cup milk'] }],
        nextCursor: 'abc',
      })
    })
    vi.stubGlobal('fetch', fetch)
    const items = await loadItems('recipes')
    expect(items.map((item) => item.id)).toEqual(['CBK-0001', 'CBK-0002'])
    expect(items[0].line).toBe("Cakes, from Quita's recipe box")
    expect(items[0].search).toContain('1/2 cup milk')
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('turns a stale write into the conflict the card shows, and sends the stamp', async () => {
    const fetch = vi.fn(async () => jsonResponse(409, { error: 'Recipe changed. Refresh before editing.' }))
    vi.stubGlobal('fetch', fetch)
    const recipe = { id: 'CBK-0001', updatedAt: '2026-10-18T00:00:00.000000Z' }
    const draft = { title: 'Stock', category: 'soups-stews', ingredients: 'water', method: 'Simmer.', notes: '' }
    const err = await saveRecipe(recipe, draft).then(
      () => null,
      (caught) => caught,
    )
    expect(err).toBeInstanceOf(ConflictError)
    expect(err.status).toBe(409)
    expect(err.message).toBe(CONFLICT_MESSAGE)
    const [, init] = fetch.mock.calls[0]
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toMatchObject({
      expected_updated_at: recipe.updatedAt,
      title: 'Stock',
      ingredients: ['water'],
    })
  })
})

describe('chat cards', async () => {
  const { chatItem } = await import('./kinds.js')
  it('use the whole first line when live cut the stored title short', () => {
    const item = chatItem({ id: 'c', title: 'Hello! My mother would like to make a soup with gnocchi and sausage. what are s', preview: 'Hello! My mother would like to make a soup with gnocchi and sausage. what are some suggestions?' })
    expect(item.card.title).toBe('Hello! My mother would like to make a soup with gnocchi and sausage. what are some suggestions?')
    expect(item.card.tip).toBe('')
  })
  it('keep a real title and show the reply opening', () => {
    const item = chatItem({ id: 'c', title: 'Soup ideas', messages: [{ role: 'user', content: 'gnocchi?' }, { role: 'assistant', content: 'Bien sûr, a zuppa toscana.' }] })
    expect(item.card).toEqual({ title: 'Soup ideas', tip: 'Bien sûr, a zuppa toscana.' })
  })
})
