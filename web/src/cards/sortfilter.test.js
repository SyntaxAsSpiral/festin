/**
 * @vitest-environment happy-dom
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import {
  defaultChoice,
  DEFAULT_CHOICE,
  STORAGE_KEY,
  applySortFilter,
  isDefaultChoice,
  pinThenArchived,
  readStoredChoice,
  summarizeChoice,
  writeStoredChoice,
} from './sortfilter.js'

function item(id, title, category, favourite = false, kind = 'formule', queuedAt = null, cookCount = 0) {
  return { id, title, raw: { id, title, category, favourite, kind, queuedAt, cookCount }, search: title.toLowerCase() }
}

function note(id, title, open) {
  return { id, title, raw: { id, text: title, open }, search: title.toLowerCase() }
}

const SAMPLE = [
  item('CBK-0003', 'Zebra Cake', 'cakes', false, 'formule', null, 0),
  item('CBK-0010', 'Apple Pie', 'pies-tarts', true, 'formule', '2026-10-18T12:00:00.000000Z', 2),
  item('CBK-0001', 'Banana Bread', 'breads', false, 'formule', '2026-10-17T12:00:00.000000Z', 0),
  item('CBK-0007', 'Carrot Cake', 'cakes', true, 'formule', null, 1),
  item('CBK-0049', 'Stir-Fry', 'misc', false, 'praxis', null, 0),
]

const NOTES = [
  note('n-z', 'Zucchini leftover', true),
  note('n-a', 'Ask for cream', false),
  note('n-b', 'Buy butter', true),
  note('n-c', 'Closed shopping', false),
]

describe('applySortFilter', () => {
  it('sorts by name A–Z by default', () => {
    const ids = applySortFilter(SAMPLE, DEFAULT_CHOICE).map((r) => r.id)
    expect(ids).toEqual(['CBK-0010', 'CBK-0001', 'CBK-0007', 'CBK-0049', 'CBK-0003'])
  })

  it('sorts by CBK number, newest first', () => {
    const ids = applySortFilter(SAMPLE, { sort: 'id-newest', category: '' }).map((r) => r.id)
    expect(ids).toEqual(['CBK-0049', 'CBK-0010', 'CBK-0007', 'CBK-0003', 'CBK-0001'])
  })

  it('sorts by CBK number, oldest first', () => {
    const ids = applySortFilter(SAMPLE, { sort: 'id-oldest', category: '' }).map((r) => r.id)
    expect(ids).toEqual(['CBK-0001', 'CBK-0003', 'CBK-0007', 'CBK-0010', 'CBK-0049'])
  })

  it('filters to formule or praxis', () => {
    expect(applySortFilter(SAMPLE, { sort: 'name', form: 'praxis' }).map((r) => r.title)).toEqual(['Stir-Fry'])
    expect(applySortFilter(SAMPLE, { sort: 'name', form: 'formule' }).map((r) => r.id)).toEqual([
      'CBK-0010',
      'CBK-0001',
      'CBK-0007',
      'CBK-0003',
    ])
  })

  it('filters to one category, then sorts', () => {
    const titles = applySortFilter(SAMPLE, { sort: 'name', category: 'cakes' }).map((r) => r.title)
    expect(titles).toEqual(['Carrot Cake', 'Zebra Cake'])
  })

  it('leaves the input array alone', () => {
    const before = SAMPLE.map((r) => r.id)
    applySortFilter(SAMPLE, { sort: 'id-newest', category: 'cakes' })
    expect(SAMPLE.map((r) => r.id)).toEqual(before)
  })

  it('filters to favourites only', () => {
    const titles = applySortFilter(SAMPLE, { sort: 'name', category: '', favouritesOnly: true }).map((r) => r.title)
    expect(titles).toEqual(['Apple Pie', 'Carrot Cake'])
  })

  it('combines favourites with a category', () => {
    const titles = applySortFilter(SAMPLE, { sort: 'name', category: 'cakes', favouritesOnly: true }).map((r) => r.title)
    expect(titles).toEqual(['Carrot Cake'])
  })

  it('filters to the to-cook queue, oldest first', () => {
    const titles = applySortFilter(SAMPLE, { sort: 'name', toCookOnly: true }).map((r) => r.title)
    expect(titles).toEqual(['Banana Bread', 'Apple Pie'])
  })

  it('filters to never cooked', () => {
    const titles = applySortFilter(SAMPLE, { sort: 'name', neverCookedOnly: true }).map((r) => r.title)
    expect(titles).toEqual(['Banana Bread', 'Stir-Fry', 'Zebra Cake'])
  })
})

describe('notes pin and archive', () => {
  it('hides archived notes by default', () => {
    const titles = applySortFilter(NOTES, DEFAULT_CHOICE, 'notes').map((r) => r.title)
    expect(titles).toEqual(['Buy butter', 'Zucchini leftover'])
  })

  it('shows archived when asked, faded sort after pinned', () => {
    const titles = applySortFilter(NOTES, { sort: 'name', showArchived: true }, 'notes').map((r) => r.title)
    expect(titles).toEqual(['Buy butter', 'Zucchini leftover', 'Ask for cream', 'Closed shopping'])
  })

  it('pinThenArchived keeps relative order within each group', () => {
    const mixed = [NOTES[1], NOTES[0], NOTES[3], NOTES[2]]
    expect(pinThenArchived(mixed).map((r) => r.id)).toEqual(['n-z', 'n-b', 'n-a', 'n-c'])
  })
})

describe('summarizeChoice', () => {
  it('is empty for the default', () => {
    expect(summarizeChoice(DEFAULT_CHOICE)).toBe('')
    expect(isDefaultChoice(DEFAULT_CHOICE)).toBe(true)
  })

  it('names a category alone', () => {
    expect(summarizeChoice({ sort: 'name', category: 'cakes' })).toBe('Cakes')
  })

  it('names favourites only', () => {
    expect(summarizeChoice({ sort: 'name', category: '', favouritesOnly: true })).toBe('Favourites only')
  })

  it('names the to-cook filter', () => {
    expect(summarizeChoice({ sort: 'name', category: '', toCookOnly: true })).toBe('To cook')
  })

  it('names the never-cooked filter', () => {
    expect(summarizeChoice({ sort: 'name', category: '', neverCookedOnly: true })).toBe('Never cooked')
  })

  it('names a form filter', () => {
    expect(summarizeChoice({ sort: 'name', form: 'praxis' })).toBe('Praxis')
    expect(summarizeChoice({ sort: 'name', form: 'formule', category: 'cakes' })).toBe('Formule, Cakes')
  })

  it('names ID order with direction', () => {
    expect(summarizeChoice({ sort: 'id-newest', category: '' })).toBe('by ID, newest first')
    expect(summarizeChoice({ sort: 'id-oldest', category: '' })).toBe('by ID, oldest first')
  })

  it('joins category and ID order', () => {
    expect(summarizeChoice({ sort: 'id-newest', category: 'cakes' })).toBe('Cakes, by ID, newest first')
  })

  it('names Show archived for notes', () => {
    expect(summarizeChoice({ sort: 'name', showArchived: true }, 'notes')).toBe('Show archived')
    expect(isDefaultChoice({ sort: 'name', showArchived: true })).toBe(false)
  })

  it('joins favourites with category and ID order', () => {
    expect(summarizeChoice({ sort: 'id-newest', category: 'cakes', favouritesOnly: true })).toBe(
      'Favourites only, Cakes, by ID, newest first',
    )
  })
})

describe('stored choice', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => localStorage.clear())

  it('defaults when nothing is stored', () => {
    expect(readStoredChoice('recipes')).toEqual(DEFAULT_CHOICE)
  })

  it('remembers a choice per kind', () => {
    writeStoredChoice('recipes', { sort: 'id-newest', category: 'cakes', favouritesOnly: true, form: 'praxis' })
    expect(localStorage.getItem(STORAGE_KEY + 'recipes')).toBeTruthy()
    expect(readStoredChoice('recipes')).toEqual({
      sort: 'id-newest',
      category: 'cakes',
      form: 'praxis',
      showArchived: false,
      favouritesOnly: true,
      toCookOnly: false,
      neverCookedOnly: false,
    })
    expect(readStoredChoice('notes')).toEqual(DEFAULT_CHOICE)
  })

  it('remembers Show archived for notes', () => {
    writeStoredChoice('notes', { sort: 'name', showArchived: true })
    expect(readStoredChoice('notes')).toEqual({
      sort: 'name',
      category: '',
      form: '',
      showArchived: true,
      favouritesOnly: false,
      toCookOnly: false,
      neverCookedOnly: false,
    })
  })

  it('fills favouritesOnly false for older stored choices', () => {
    localStorage.setItem(STORAGE_KEY + 'recipes', JSON.stringify({ sort: 'name', category: 'cakes' }))
    expect(readStoredChoice('recipes')).toEqual({
      sort: 'name',
      category: 'cakes',
      form: '',
      showArchived: false,
      favouritesOnly: false,
      toCookOnly: false,
      neverCookedOnly: false,
    })
  })

  it('ignores a corrupt payload', () => {
    localStorage.setItem(STORAGE_KEY + 'recipes', '{nope')
    expect(readStoredChoice('recipes')).toEqual(DEFAULT_CHOICE)
  })

  it('ignores unknown sort or category keys', () => {
    localStorage.setItem(STORAGE_KEY + 'recipes', JSON.stringify({ sort: 'bogus', category: 'nope' }))
    expect(readStoredChoice('recipes')).toEqual(DEFAULT_CHOICE)
  })
})

describe('chats sort by date', () => {
  const chat = (id, title, createdAt, updatedAt) => ({ id, title, raw: { id, createdAt, updatedAt }, search: title })
  const CHATS = [
    chat('a', 'Old soup', '2026-09-05', null),
    chat('b', 'Undated', null, null),
    chat('c', 'Tonight', '2026-10-19T01:00:00Z', '2026-10-19T06:00:00Z'),
    chat('d', 'Last week', '2026-10-12', null),
  ]

  it('opens on the most recent first, undated last', () => {
    expect(defaultChoice('chats').sort).toBe('date-newest')
    expect(applySortFilter(CHATS, defaultChoice('chats'), 'chats').map((c) => c.id)).toEqual(['c', 'd', 'a', 'b'])
    expect(isDefaultChoice(defaultChoice('chats'), 'chats')).toBe(true)
    expect(summarizeChoice(defaultChoice('chats'), 'chats')).toBe('')
  })

  it('can sort oldest first, undated still last', () => {
    const choice = { ...defaultChoice('chats'), sort: 'date-oldest' }
    expect(applySortFilter(CHATS, choice, 'chats').map((c) => c.id)).toEqual(['a', 'd', 'c', 'b'])
    expect(summarizeChoice(choice, 'chats')).toBe('oldest first')
  })

  it('reads a fresh device as most recent first', () => {
    localStorage.removeItem(STORAGE_KEY + 'chats')
    expect(readStoredChoice('chats').sort).toBe('date-newest')
  })
})
