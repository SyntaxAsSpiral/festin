/**
 * @vitest-environment happy-dom
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { DEFAULT_TYPE_CPS, SPEED_KEY, TYPE_CPS_MAX, TYPE_CPS_MIN } from './constants.js'
import { readWritingSpeed, writeWritingSpeed } from './speed.js'

describe('writing speed storage', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('defaults to 55 and clamps the saved value', () => {
    expect(readWritingSpeed()).toBe(DEFAULT_TYPE_CPS)
    expect(writeWritingSpeed(12)).toBe(TYPE_CPS_MIN)
    expect(localStorage.getItem(SPEED_KEY)).toBe(String(TYPE_CPS_MIN))
    expect(writeWritingSpeed(200)).toBe(TYPE_CPS_MAX)
    expect(readWritingSpeed()).toBe(TYPE_CPS_MAX)
    expect(writeWritingSpeed(70)).toBe(70)
  })
})
