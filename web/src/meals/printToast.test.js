import { describe, expect, it } from 'vitest'
import { printTarget, toastForPrintResult } from './printToast.js'

describe('print toast outcomes', () => {
  it('maps printed, already printed, uncertain, and plain errors', () => {
    expect(toastForPrintResult({ ok: true, body: { status: 'printed', message: 'Printed.' } })).toBe(
      'Printed.',
    )
    expect(
      toastForPrintResult({
        ok: true,
        body: { status: 'printed', message: 'No additional print sent.', slip_id: 'abc' },
      }),
    ).toBe('Already printed.')
    expect(
      toastForPrintResult({
        ok: true,
        body: {
          status: 'uncertain',
          message:
            'The printer did not confirm. Check it before asking for another copy; some paper may have printed.',
        },
      }),
    ).toMatch(/uncertain|printer/)
    expect(toastForPrintResult({ ok: false, error: 'Print receiver token is not set.' })).toBe(
      'Print receiver token is not set.',
    )
  })

  it('prints the open recipe, else the week on Meals', () => {
    const week = { weekStart: '2026-10-17' }
    expect(printTarget({ onMeals: true, printerOn: false, plan: week })).toEqual({ message: 'The printer plugin is off.' })
    expect(printTarget({ onMeals: false, printerOn: true, card: { kind: 'recipes', id: 'CBK-0933' } })).toMatchObject({
      action: 'print-recipe',
      body: { recipe_id: 'CBK-0933' },
    })
    expect(printTarget({ onMeals: false, printerOn: true, card: { kind: 'notes', id: 'n1' } }).message).toBeTruthy()
    expect(printTarget({ onMeals: false, printerOn: true, plan: week }).message).toBe('Open a recipe, or the week on Meals, to print.')
    expect(printTarget({ onMeals: true, printerOn: true, plan: null })).toEqual({ message: 'Open a week on Meals first.' })
    expect(printTarget({ onMeals: true, printerOn: true, plan: week })).toMatchObject({ action: 'print-dinner' })
  })

})
