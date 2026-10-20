import { describe, expect, it } from 'vitest'
import { formatLogWhen } from './logDate.js'
import { conversationSummary, entryMeta, RECIPE_EVENT_KINDS } from './logEntries.js'

describe('formatLogWhen', () => {
  it('shows around the week of for approximate dates, with no clock time', () => {
    expect(formatLogWhen('2026-10-17T12:00:00.000000Z', { approx: true })).toBe(
      'around the week of 17 Oct',
    )
    expect(formatLogWhen('2026-10-17T12:00:00.000000Z', { approx: true })).not.toMatch(/AM|PM|:/)
  })

  it('keeps weekday and time for real dated entries', () => {
    const line = formatLogWhen('2026-10-17T11:56:46.122772Z', { approx: false })
    expect(line).toMatch(/^Sat 17 Oct · /)
    expect(line).toMatch(/\d/)
    expect(line).not.toMatch(/^around the week of/)
  })

  it('omits time for day-end week stamps', () => {
    expect(formatLogWhen('2026-10-23T23:59:59.000000Z')).toBe('Fri 23 Oct')
  })
})

describe('entryMeta', () => {
  it('labels and classes the new kitchen log kinds', () => {
    expect(entryMeta('recipe_cooked')).toEqual({
      label: 'Recipe first cooked',
      rowClass: 'tl-cooked',
    })
    expect(entryMeta('note_archived')).toEqual({
      label: 'Note archived',
      rowClass: 'tl-archived',
    })
    expect(entryMeta('recipe_favourited')).toEqual({
      label: 'Recipe favourited',
      rowClass: 'tl-fav',
    })
    expect(entryMeta('recipe_planned')).toEqual({
      label: 'Recipe planned',
      rowClass: 'tl-planned',
    })
    expect(entryMeta('photo_added')).toEqual({
      label: 'Recipe photo added',
      rowClass: 'tl-photo',
    })
    expect(entryMeta('recipe_added').label).toBe('Recipe added')
    expect(entryMeta('recipe_edited').label).toBe('Recipe updated')
  })

  it('treats photo and favourite events as recipe navigations', () => {
    expect(RECIPE_EVENT_KINDS.has('photo_added')).toBe(true)
    expect(RECIPE_EVENT_KINDS.has('recipe_favourited')).toBe(true)
    expect(RECIPE_EVENT_KINDS.has('recipe_planned')).toBe(true)
    expect(RECIPE_EVENT_KINDS.has('note_archived')).toBe(false)
  })
})

describe('conversationSummary', () => {
  it('counts folded imported chats for the week line', () => {
    expect(conversationSummary([])).toBe('')
    expect(conversationSummary([{ id: 'a' }])).toBe('1 conversation')
    expect(conversationSummary([{ id: 'a' }, { id: 'b' }])).toBe('2 conversations')
  })
})
