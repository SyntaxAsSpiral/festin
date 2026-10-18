import { describe, expect, it } from 'vitest'
import { formatLogWhen } from './logDate.js'

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
