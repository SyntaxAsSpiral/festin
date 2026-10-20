/** Kitchen Log entry labels (record type, then action) and timeline classes.
 *  Loose rows of the household's current week group under a day heading.
 *  Consecutive events of one kind on one day fold; key kinds keep a full row. */

import { dateTimeFormat, householdDate, weekStartOn } from '../cards/kinds.js'
import { weekDates } from './plan.js'
import { formatLogWhen } from './logDate.js'

export const RECIPE_EVENT_KINDS = new Set([
  'recipe_added',
  'recipe_edited',
  'recipe_cooked',
  'recipe_favourited',
  'recipe_planned',
  'photo_added',
])

// Full row with a plate. Everything else is one quiet line.
const KEY_KINDS = new Set([
  'recipe_cooked',
  'recipe_favourited',
  'recipe_planned',
  'recipe_added',
  'note_created',
  'chat',
])

const META = {
  recipe_added: { label: 'Recipe added', rowClass: 'tl-r', modClass: 'tl-a' },
  recipe_edited: { label: 'Recipe updated', rowClass: 'tl-r', modClass: 'tl-u' },
  recipe_cooked: { label: 'Cooked', rowClass: 'tl-cooked' },
  recipe_favourited: { label: 'Recipe favourited', rowClass: 'tl-fav' },
  recipe_planned: { label: 'Recipe planned', rowClass: 'tl-planned' },
  photo_added: { label: 'Recipe photo added', rowClass: 'tl-photo' },
  note_created: { label: 'Note created', rowClass: 'tl-c' },
  note_archived: { label: 'Note archived', rowClass: 'tl-archived' },
  chat: { label: 'Chat started', rowClass: 'tl-chat' },
}

const NAME_CAP = 3

export function entryMeta(kind) {
  return META[kind] || { label: 'Recipe updated', rowClass: 'tl-r', modClass: 'tl-u' }
}

export function entryWeight(kind) {
  return KEY_KINDS.has(kind) ? 'key' : 'routine'
}

/** Quiet ordinal for a cook past the first: "3rd time". Empty when ≤ 1. */
export function cookOrdinalDetail(ordinal) {
  const n = Number(ordinal)
  if (!Number.isFinite(n) || n < 2) return ''
  const mod100 = n % 100
  const mod10 = n % 10
  const suf =
    mod100 >= 11 && mod100 <= 13 ? 'th' : mod10 === 1 ? 'st' : mod10 === 2 ? 'nd' : mod10 === 3 ? 'rd' : 'th'
  return `${n}${suf} time`
}

export function conversationSummary(conversations) {
  const n = (conversations || []).length
  if (!n) return ''
  return `${n} conversation${n === 1 ? '' : 's'}`
}

function zoneOf(timeZone) {
  if (!timeZone || timeZone === 'auto') return undefined
  return timeZone
}

function withZone(timeZone, options) {
  const zone = zoneOf(timeZone)
  return zone ? { ...options, timeZone: zone } : options
}

export function householdDayKey(iso, timeZone) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10)
  return householdDate(timeZone, d)
}

export function formatDayHeading(dayKey) {
  const [y, m, d] = String(dayKey || '').split('-').map(Number)
  if (!y || !m || !d) return String(dayKey || '')
  const date = new Date(Date.UTC(y, m - 1, d, 12))
  const weekday = dateTimeFormat('en-GB', { weekday: 'long', timeZone: 'UTC' }).format(date)
  const month = dateTimeFormat('en-GB', { month: 'long', timeZone: 'UTC' }).format(date)
  return `${weekday} ${d} ${month}`
}

function clockParts(iso, timeZone) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  let parts
  try {
    parts = dateTimeFormat('en-US', withZone(timeZone, {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    })).formatToParts(d)
  } catch {
    parts = dateTimeFormat('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    }).formatToParts(d)
  }
  const get = (type) => parts.find((p) => p.type === type)?.value || ''
  const hour = get('hour')
  if (!hour) return null
  return { hour, minute: get('minute'), mer: get('dayPeriod').toLowerCase() }
}

export function formatClock(iso, timeZone) {
  const parts = clockParts(iso, timeZone)
  if (!parts) return ''
  return `${parts.hour}:${parts.minute} ${parts.mer}`
}

/** Earliest–latest. One meridiem when they share it: "6:02–6:06 pm". */
export function formatClockRange(earlier, later, timeZone) {
  const a = clockParts(earlier, timeZone)
  const b = clockParts(later, timeZone)
  if (!a || !b) return ''
  if (a.hour === b.hour && a.minute === b.minute && a.mer === b.mer) {
    return `${a.hour}:${a.minute} ${a.mer}`
  }
  if (a.mer && a.mer === b.mer) return `${a.hour}:${a.minute}–${b.hour}:${b.minute} ${a.mer}`
  return `${a.hour}:${a.minute} ${a.mer}–${b.hour}:${b.minute} ${b.mer}`
}

export function formatLogDay(iso, timeZone) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  try {
    return d
      .toLocaleDateString('en-GB', withZone(timeZone, { weekday: 'short', day: 'numeric', month: 'short' }))
      .replace(/,/g, '')
  } catch {
    return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }).replace(/,/g, '')
  }
}

export function entryWhen(entry, { underDay = false, timeZone } = {}) {
  if (!entry) return ''
  if (entry.dateApprox) return formatLogWhen(entry.at, { approx: true })
  const clock = formatClock(entry.at, timeZone)
  if (underDay) return clock
  const day = formatLogDay(entry.at, timeZone)
  if (day && clock) return `${day} · ${clock}`
  return day || clock || formatLogWhen(entry.at)
}

function singleTail(entry) {
  const bits = [entryMeta(entry.kind).label]
  if (entry.kind === 'photo_added' && entry.detail) bits.push(String(entry.detail))
  if (entry.kind === 'recipe_cooked') {
    const ordinal = cookOrdinalDetail(entry.ordinal)
    if (ordinal) bits.push(ordinal)
  }
  return bits.join(' · ')
}

function foldNoun(kind, n) {
  const pairs = {
    photo_added: ['photo', 'photos'],
    note_created: ['note', 'notes'],
    note_archived: ['note', 'notes'],
  }
  const [one, many] = pairs[kind] || ['card', 'cards']
  return n === 1 ? one : many
}

function nameList(events) {
  const names = []
  for (const event of events) {
    const title = String(event.title || '').trim()
    if (title) names.push(title)
  }
  if (names.length <= NAME_CAP) return names.join(', ')
  return names.slice(0, NAME_CAP).join(', ') + '…'
}

function sameSubject(events) {
  if (events[0].kind === 'chat') return false
  const ids = events.map((event) => event.id).filter((id) => id != null && id !== '')
  return ids.length === events.length && new Set(ids).size === 1
}

/** Bead line for a fold of two or more. Chats count; one recipe repeats; a mix lists cards. */
export function foldSummary(events) {
  const n = events.length
  const kind = events[0].kind
  if (kind === 'chat') return `${n} chats`
  if (sameSubject(events)) {
    const title = String(events[0].title || '').trim()
    return `${n}× · ${title}`
  }
  const label = entryMeta(kind).label
  const noun = foldNoun(kind, n)
  const names = nameList(events)
  return names ? `${label} · ${n} ${noun}: ${names}` : `${label} · ${n} ${noun}`
}

function spanOf(events) {
  let earliest = events[0]
  let latest = events[0]
  for (const event of events) {
    if (String(event.at) < String(earliest.at)) earliest = event
    if (String(event.at) > String(latest.at)) latest = event
  }
  return { earliest, latest }
}

function describeFold(events, ctx) {
  const kind = events[0].kind
  const weight = entryWeight(kind)
  const summary = foldSummary(events)
  const label = entryMeta(kind).label
  const n = events.length
  const { earliest, latest } = spanOf(events)
  const newest = latest
  const approx = Boolean(newest.dateApprox)
  const range = approx ? '' : formatClockRange(earliest.at, newest.at, ctx.timeZone)
  const clock = approx ? '' : formatClock(newest.at, ctx.timeZone)
  const repeat = sameSubject(events)
  const names = nameList(events)
  let timeCore
  if (approx) timeCore = formatLogWhen(newest.at, { approx: true })
  else if (kind === 'chat') timeCore = clock
  else timeCore = range || clock
  const day = ctx.underDay || approx ? '' : formatLogDay(newest.at, ctx.timeZone)
  const timeLabel = day ? `${day} · ${timeCore}` : timeCore

  let metaTail = label
  let title = ''
  let quiet = ''
  let more = ''
  if (kind === 'chat') {
    metaTail = summary
    title = newest.title || 'Conversation'
    const extra = n - 1
    if (extra > 0) more = range && range !== clock ? `and ${extra} more, ${range}` : `and ${extra} more`
  } else if (repeat) {
    metaTail = label
    if (weight === 'key') title = summary
    else quiet = summary
  } else {
    metaTail = `${label} · ${n} ${foldNoun(kind, n)}`
    if (weight === 'key') title = names
    else quiet = names
  }

  const category =
    weight === 'key' && newest.category && events.every((event) => event.category === newest.category)
      ? newest.category
      : ''

  return {
    type: 'fold',
    kind,
    weight,
    events,
    underDay: ctx.underDay,
    summary,
    timeLabel,
    metaTail,
    title,
    quiet,
    more,
    category,
  }
}

// Chats and routine kinds fold a whole run. A key event folds only with the same
// record, so three cooks of one recipe become 3× and the next recipe stays a row.
function runKey(event) {
  const approx = event.dateApprox ? 'a' : 't'
  if (event.kind === 'chat' || entryWeight(event.kind) === 'routine') return `${event.kind}|${approx}`
  return `${event.kind}|${approx}|${event.id || ''}`
}

function foldRun(slice, ctx) {
  const out = []
  let i = 0
  while (i < slice.length) {
    const key = runKey(slice[i])
    let j = i + 1
    while (j < slice.length && runKey(slice[j]) === key) j += 1
    const events = slice.slice(i, j)
    if (events.length >= 2) out.push(describeFold(events, ctx))
    else {
      const entry = events[0]
      out.push({
        type: 'entry',
        entry,
        kind: entry.kind,
        weight: entryWeight(entry.kind),
        underDay: ctx.underDay,
        timeLabel: entryWhen(entry, ctx),
        metaTail: singleTail(entry),
      })
    }
    i = j
  }
  return out
}

function currentWeekSet(timeZone, weekStart, now) {
  const today = householdDate(timeZone, now)
  const start = weekStartOn(today, weekStart || 'sat')
  return new Set(weekDates(start))
}

/**
 * Newest-first entries → blocks.
 * A week box breaks a run and keeps its own dates.
 * Day headings cover loose events whose household day is in the current week.
 * A fold is two or more consecutive events on that day: chats and routine kinds
 * fold the whole run; a key event folds only with the same record.
 * An approximate chat does not fold with a timed one.
 */
export function groupLogEntries(entries, { timeZone, weekStart = 'sat', now = new Date() } = {}) {
  const list = entries || []
  const weekDays = currentWeekSet(timeZone, weekStart, now)
  const blocks = []
  let i = 0
  while (i < list.length) {
    if (list[i].kind === 'week') {
      blocks.push({ type: 'week', entry: list[i] })
      i += 1
      continue
    }
    let j = i
    while (j < list.length && list[j].kind !== 'week') j += 1
    const run = list.slice(i, j)
    let k = 0
    while (k < run.length) {
      const day = householdDayKey(run[k].at, timeZone)
      let m = k + 1
      while (m < run.length && householdDayKey(run[m].at, timeZone) === day) m += 1
      const slice = run.slice(k, m)
      const underDay = Boolean(day) && weekDays.has(day)
      if (underDay) blocks.push({ type: 'day', day, label: formatDayHeading(day) })
      blocks.push(...foldRun(slice, { underDay, timeZone }))
      k = m
    }
    i = j
  }
  return blocks
}

export function foldKey(events) {
  // The newest event stays put as older pages append, so an open fold does not remount.
  const first = events[0]
  return `${first.kind}:${first.id}:${first.at}`
}
