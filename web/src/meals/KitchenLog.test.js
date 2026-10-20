import { describe, expect, it } from 'vitest'
import { dateTimeFormatCache, householdDate } from '../cards/kinds.js'
import { formatLogWhen } from './logDate.js'
import {
  conversationSummary,
  cookOrdinalDetail,
  entryMeta,
  entryWeight,
  formatClock,
  formatDayHeading,
  groupLogEntries,
  RECIPE_EVENT_KINDS,
} from './logEntries.js'

const ZONE = 'America/Los_Angeles'
const NOW = new Date('2026-10-19T18:00:00.000Z')
const CTX = { timeZone: ZONE, weekStart: 'sat', now: NOW }

function ev(fields) {
  return { id: 'x', title: 'Title', at: '2026-10-20T04:34:00.000Z', ...fields }
}

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
      label: 'Cooked',
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

describe('cookOrdinalDetail', () => {
  it('stays quiet for the first cook and names later ones', () => {
    expect(cookOrdinalDetail(0)).toBe('')
    expect(cookOrdinalDetail(1)).toBe('')
    expect(cookOrdinalDetail(2)).toBe('2nd time')
    expect(cookOrdinalDetail(3)).toBe('3rd time')
    expect(cookOrdinalDetail(11)).toBe('11th time')
    expect(cookOrdinalDetail(21)).toBe('21st time')
  })
})

describe('conversationSummary', () => {
  it('counts folded imported chats for the week line', () => {
    expect(conversationSummary([])).toBe('')
    expect(conversationSummary([{ id: 'a' }])).toBe('1 conversation')
    expect(conversationSummary([{ id: 'a' }, { id: 'b' }])).toBe('2 conversations')
  })
})

describe('entryWeight', () => {
  it('keeps key events full and routine events quiet', () => {
    for (const kind of ['recipe_cooked', 'recipe_favourited', 'recipe_planned', 'recipe_added', 'note_created', 'chat']) {
      expect(entryWeight(kind)).toBe('key')
    }
    for (const kind of ['recipe_edited', 'photo_added', 'note_archived']) {
      expect(entryWeight(kind)).toBe('routine')
    }
  })
})

describe('groupLogEntries', () => {
  it('groups the current week under a household day and leaves the clock on the row', () => {
    const blocks = groupLogEntries(
      [
        ev({ kind: 'chat', id: 'c1', title: 'Dry brine', at: '2026-10-20T04:34:00.000Z' }),
        ev({
          kind: 'recipe_cooked',
          id: 'pie',
          title: 'Pot Pie',
          category: 'pies-tarts',
          at: '2026-10-20T02:15:00.000Z',
        }),
      ],
      CTX,
    )
    expect(blocks.map((block) => block.type)).toEqual(['day', 'entry', 'entry'])
    expect(blocks[0].label).toBe('Monday 19 October')
    expect(blocks[1].timeLabel).toBe('9:34 pm')
    expect(blocks[1].metaTail).toBe('Chat started')
    expect(blocks[1].underDay).toBe(true)
    expect(blocks[1].weight).toBe('key')
    expect(blocks[2].timeLabel).toBe('7:15 pm')
  })

  it('does not head a week box, and an older loose row keeps its date', () => {
    const blocks = groupLogEntries(
      [
        ev({ kind: 'chat', id: 'c1', at: '2026-10-20T04:34:00.000Z' }),
        { kind: 'week', at: '2026-10-16T23:59:59.000000Z', weekStart: '2026-10-10', nights: [], conversations: [] },
        ev({ kind: 'recipe_cooked', id: 'old', title: 'Stew', at: '2026-10-16T20:00:00.000Z' }),
      ],
      CTX,
    )
    expect(blocks.map((block) => block.type)).toEqual(['day', 'entry', 'week', 'entry'])
    expect(blocks[2].entry.weekStart).toBe('2026-10-10')
    expect(blocks[3].underDay).toBe(false)
    expect(blocks[3].timeLabel).toBe('Fri 16 Oct · 1:00 pm')
  })

  it('folds a run of one kind, and splits on kind, day, recipe, and a single event', () => {
    const sameDay = groupLogEntries(
      [
        ev({ kind: 'recipe_edited', id: 'a', title: 'A', at: '2026-10-20T03:00:00.000Z' }),
        ev({ kind: 'recipe_edited', id: 'b', title: 'B', at: '2026-10-20T02:00:00.000Z' }),
        ev({ kind: 'recipe_cooked', id: 'c', title: 'C', at: '2026-10-20T01:30:00.000Z' }),
      ],
      CTX,
    )
    expect(sameDay.map((block) => block.type)).toEqual(['day', 'fold', 'entry'])
    expect(sameDay[1].events).toHaveLength(2)
    expect(sameDay[2].type).toBe('entry')

    const cooks = groupLogEntries(
      [
        ev({ kind: 'recipe_cooked', id: 'pie', title: 'Pot Pie', at: '2026-10-20T03:10:00.000Z' }),
        ev({ kind: 'recipe_cooked', id: 'zuni', title: 'Zuni Chicken & Bread Salad', at: '2026-10-20T03:00:00.000Z' }),
        ev({ kind: 'recipe_cooked', id: 'zuni', title: 'Zuni Chicken & Bread Salad', at: '2026-10-20T02:00:00.000Z' }),
      ],
      CTX,
    )
    expect(cooks.map((block) => block.type)).toEqual(['day', 'entry', 'fold'])
    expect(cooks[1].entry.id).toBe('pie')
    expect(cooks[2].summary).toBe('2× · Zuni Chicken & Bread Salad')

    const twoDays = groupLogEntries(
      [
        ev({ kind: 'recipe_cooked', id: 'a', title: 'A', at: '2026-10-20T03:00:00.000Z' }),
        ev({ kind: 'recipe_cooked', id: 'b', title: 'B', at: '2026-10-19T01:00:00.000Z' }),
      ],
      CTX,
    )
    expect(twoDays.map((block) => block.type)).toEqual(['day', 'entry', 'day', 'entry'])
    expect(twoDays[0].label).toBe('Monday 19 October')
    expect(twoDays[2].label).toBe('Sunday 18 October')

    const single = groupLogEntries(
      [ev({ kind: 'recipe_cooked', id: 'only', title: 'Only', at: '2026-10-20T03:00:00.000Z' })],
      CTX,
    )
    expect(single.map((block) => block.type)).toEqual(['day', 'entry'])
  })

  it('does not fold an approximate chat into a timed one', () => {
    const blocks = groupLogEntries(
      [
        ev({ kind: 'chat', id: 'a', title: 'Imported', dateApprox: true, at: '2026-10-20T04:00:00.000Z' }),
        ev({ kind: 'chat', id: 'b', title: 'Timed', at: '2026-10-20T03:00:00.000Z' }),
      ],
      CTX,
    )
    expect(blocks.filter((block) => block.type === 'fold')).toHaveLength(0)
    expect(blocks.filter((block) => block.type === 'entry')).toHaveLength(2)
  })

  it('does not fold across a week box', () => {
    const blocks = groupLogEntries(
      [
        ev({ kind: 'chat', id: 'c1', title: 'One', at: '2026-10-20T04:00:00.000Z' }),
        ev({ kind: 'chat', id: 'c2', title: 'Two', at: '2026-10-20T03:00:00.000Z' }),
        { kind: 'week', at: '2026-10-20T02:30:00.000Z', weekStart: '2026-10-10', nights: [] },
        ev({ kind: 'chat', id: 'c3', title: 'Three', at: '2026-10-20T02:00:00.000Z' }),
      ],
      CTX,
    )
    const folds = blocks.filter((block) => block.type === 'fold')
    expect(folds).toHaveLength(1)
    expect(folds[0].events.map((event) => event.id)).toEqual(['c1', 'c2'])
    expect(blocks.filter((block) => block.type === 'entry').map((block) => block.entry.id)).toEqual(['c3'])
  })

  it('counts a repeated recipe, a mixed run, and a chat run', () => {
    const cooks = groupLogEntries(
      [1, 2, 3].map((n) =>
        ev({
          kind: 'recipe_cooked',
          id: 'zuni',
          title: 'Zuni Chicken & Bread Salad',
          category: 'chicken',
          at: `2026-10-20T0${n}:00:00.000Z`,
        }),
      ),
      CTX,
    )
    const cookFold = cooks.find((block) => block.type === 'fold')
    expect(cookFold.summary).toBe('3× · Zuni Chicken & Bread Salad')
    expect(cookFold.weight).toBe('key')
    expect(cookFold.timeLabel).toBe('6:00–8:00 pm')

    const titles = ['Phyllo', 'Fond', 'Sherry', 'Mint', 'Beans']
    const edits = groupLogEntries(
      titles.map((title, i) =>
        ev({
          kind: 'recipe_edited',
          id: 'r' + i,
          title,
          at: `2026-10-20T01:${String(6 - i).padStart(2, '0')}:00.000Z`,
        }),
      ),
      CTX,
    )
    const editFold = edits.find((block) => block.type === 'fold')
    expect(editFold.summary).toBe('Recipe updated · 5 cards: Phyllo, Fond, Sherry…')
    expect(editFold.weight).toBe('routine')
    expect(editFold.timeLabel).toBe('6:02–6:06 pm')
    expect(editFold.quiet).toBe('Phyllo, Fond, Sherry…')

    const chats = groupLogEntries(
      Array.from({ length: 6 }, (_, i) =>
        ev({
          kind: 'chat',
          id: 'c' + i,
          title: i === 0 ? 'Since it says the chicken is dry-brined for days…' : 'Later ' + i,
          at: `2026-10-20T0${i + 1}:00:00.000Z`,
        }),
      ),
      CTX,
    )
    const chatFold = chats.find((block) => block.type === 'fold')
    expect(chatFold.summary).toBe('6 chats')
    expect(chatFold.weight).toBe('key')
    expect(chatFold.title).toBe('Later 5')
    expect(chatFold.timeLabel).toBe('11:00 pm')
    expect(chatFold.more).toBe('and 5 more, 6:00–11:00 pm')
  })
})

describe('date formatter cache', () => {
  it('builds each DateTimeFormat once per locale, options, and zone', () => {
    dateTimeFormatCache.clear()
    const day = new Date('2026-06-01T15:04:00Z')
    expect(householdDate('UTC', day)).toBe('2026-06-01')
    expect(householdDate('UTC', new Date('2026-06-02T03:00:00Z'))).toBe('2026-06-02')
    expect(dateTimeFormatCache.size).toBe(1)
    expect(householdDate('Europe/Paris', day)).toBe('2026-06-01')
    expect(dateTimeFormatCache.size).toBe(2)
    expect(formatDayHeading('2026-06-01')).toBe('Monday 1 June')
    formatDayHeading('2026-07-01')
    expect(dateTimeFormatCache.size).toBe(4)
    expect(formatClock('2026-06-01T15:04:00Z', 'UTC')).toBe('3:04 pm')
    formatClock('2026-06-01T18:04:00Z', 'UTC')
    expect(dateTimeFormatCache.size).toBe(5)
    formatClock('2026-06-01T15:04:00Z', 'Europe/Paris')
    formatClock('2026-06-01T18:04:00Z', 'Europe/Paris')
    expect(dateTimeFormatCache.size).toBe(6)
  })
})
