import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import {
  DEFAULT_SLIP_TITLE,
  draftToSaveBody,
  parseRecipeId,
  planToDraft,
  savePlan,
  slipTitleOf,
  weekStartFor,
  isoDate,
} from './plan.js'

describe('slip mapping', () => {
  it('pads recipe ids from short forms', () => {
    expect(parseRecipeId('12')).toBe('CBK-0012')
    expect(parseRecipeId('cbk 12')).toBe('CBK-0012')
    expect(parseRecipeId('CBK-0012')).toBe('CBK-0012')
    expect(parseRecipeId('CBK-933')).toBe('CBK-0933')
    expect(parseRecipeId('')).toBe(null)
    expect(parseRecipeId('not-an-id')).toBe(null)
  })

  it('falls back to LE FESTIN when the week has no title', () => {
    expect(slipTitleOf({ slipTitle: '' })).toBe(DEFAULT_SLIP_TITLE)
    expect(slipTitleOf({ slipTitle: '  ' })).toBe(DEFAULT_SLIP_TITLE)
    expect(slipTitleOf({ slipQuote: 'Bon appétit' })).toBe('Bon appétit')
    expect(slipTitleOf({ slipTitle: 'Que la chaleur' })).toBe('Que la chaleur')
  })

  it('maps a plan onto seven editable nights', () => {
    const plan = {
      weekStart: '2026-10-17',
      slipTitle: 'Que la chaleur de la table console et rassemble.',
      updatedAt: '2026-10-17T11:56:46.122772+00:00',
      days: [
        { day: 'sat', date: '2026-10-17', recipe: null, title: 'Chicken Salad', ingredients: [], cooked: false },
        { day: 'sun', date: '2026-10-18', recipe: 'CBK-0933', title: 'Venison Stroganoff', ingredients: ['onion'], cooked: true },
      ],
    }
    const draft = planToDraft(plan)
    expect(draft.slipTitle).toBe('Que la chaleur de la table console et rassemble.')
    expect(draft.days).toHaveLength(7)
    expect(draft.days[0]).toMatchObject({ title: 'Chicken Salad', recipe: null, cooked: false })
    expect(draft.days[1]).toMatchObject({ title: 'Venison Stroganoff', recipe: 'CBK-0933', cooked: true })
    expect(draft.days[2].date).toBe('2026-10-19')
    expect(draft.updatedAt).toBe(plan.updatedAt)
  })

  it('sends expected_updated_at with the seven nights', () => {
    const draft = planToDraft({
      weekStart: '2026-10-17',
      slipTitle: 'LE FESTIN',
      updatedAt: 'stamp-1',
      days: Array.from({ length: 7 }, (_, i) => ({
        day: 'sat',
        date: `2026-10-${17 + i}`,
        title: i === 0 ? 'Soup' : '',
        recipe: null,
        ingredients: [],
        cooked: false,
      })),
    })
    const body = draftToSaveBody(draft)
    expect(body.expected_updated_at).toBe('stamp-1')
    expect(body.weekStart).toBe('2026-10-17')
    expect(body.days).toHaveLength(7)
    expect(body.days[0].title).toBe('Soup')
  })

  it('starts a Saturday week on Saturday', () => {
    expect(isoDate(weekStartFor('2026-10-18', 'sat'))).toBe('2026-10-17')
    expect(isoDate(weekStartFor('2026-10-17', 'sat'))).toBe('2026-10-17')
  })
})

describe('409 conflict path', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 409,
        json: async () => ({
          error: 'This week was saved from another device. Open the week to load the latest dinners before saving.',
        }),
      })),
    )
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('raises a conflict error with status 409', async () => {
    const draft = planToDraft({
      weekStart: '2026-10-17',
      slipTitle: 'LE FESTIN',
      updatedAt: 'stale',
      days: Array.from({ length: 7 }, (_, i) => ({
        day: 'sat',
        date: `2026-10-${17 + i}`,
        title: '',
        recipe: null,
        ingredients: [],
        cooked: false,
      })),
    })
    await expect(savePlan(draft)).rejects.toMatchObject({ message: 'conflict', status: 409 })
    expect(fetch).toHaveBeenCalledWith(
      '/api/plan',
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('"expected_updated_at":"stale"'),
      }),
    )
  })
})

describe('frieze courses', async () => {
  const { courseOrder } = await import('./Frieze.jsx')
  it('deals each meal as soup, salad, main, side, dessert', () => {
    const order = courseOrder([['s1', 's2'], ['a1', 'a2'], ['m1', 'm2'], ['x1', 'x2'], ['d1', 'd2', 'd3']])
    expect(order).toEqual(['s1', 'a1', 'm1', 'x1', 'd1', 's2', 'a2', 'm2', 'x2', 'd2'])
  })
})
