/**
 * @vitest-environment happy-dom
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import {
  DEFAULT_CHOICE,
  STORAGE_KEY,
  applySortFilter,
  isDefaultChoice,
  readStoredChoice,
  summarizeChoice,
  writeStoredChoice,
} from './sortfilter.js'

function item(id, title, category, favourite = false) {
  return { id, title, raw: { id, title, category, favourite }, search: title.toLowerCase() }
}

const SAMPLE = [
  item('CBK-0003', 'Zebra Cake', 'cakes'),
  item('CBK-0010', 'Apple Pie', 'pies-tarts', true),
  item('CBK-0001', 'Banana Bread', 'breads'),
  item('CBK-0007', 'Carrot Cake', 'cakes', true),
]

describe('applySortFilter', () => {
  it('sorts by name A–Z by default', () => {
    const ids = applySortFilter(SAMPLE, DEFAULT_CHOICE).map((r) => r.id)
    expect(ids).toEqual(['CBK-0010', 'CBK-0001', 'CBK-0007', 'CBK-0003'])
  })

  it('sorts by CBK number, newest first', () => {
    const ids = applySortFilter(SAMPLE, { sort: 'id-newest', category: '' }).map((r) => r.id)
    expect(ids).toEqual(['CBK-0010', 'CBK-0007', 'CBK-0003', 'CBK-0001'])
  })

  it('sorts by CBK number, oldest first', () => {
    const ids = applySortFilter(SAMPLE, { sort: 'id-oldest', category: '' }).map((r) => r.id)
    expect(ids).toEqual(['CBK-0001', 'CBK-0003', 'CBK-0007', 'CBK-0010'])
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

  it('names ID order with direction', () => {
    expect(summarizeChoice({ sort: 'id-newest', category: '' })).toBe('by ID, newest first')
    expect(summarizeChoice({ sort: 'id-oldest', category: '' })).toBe('by ID, oldest first')
  })

  it('joins category and ID order', () => {
    expect(summarizeChoice({ sort: 'id-newest', category: 'cakes' })).toBe('Cakes, by ID, newest first')
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
    writeStoredChoice('recipes', { sort: 'id-newest', category: 'cakes', favouritesOnly: true })
    expect(localStorage.getItem(STORAGE_KEY + 'recipes')).toBeTruthy()
    expect(readStoredChoice('recipes')).toEqual({ sort: 'id-newest', category: 'cakes', favouritesOnly: true })
    expect(readStoredChoice('notes')).toEqual(DEFAULT_CHOICE)
  })

  it('fills favouritesOnly false for older stored choices', () => {
    localStorage.setItem(STORAGE_KEY + 'recipes', JSON.stringify({ sort: 'name', category: 'cakes' }))
    expect(readStoredChoice('recipes')).toEqual({ sort: 'name', category: 'cakes', favouritesOnly: false })
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
