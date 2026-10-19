import { describe, expect, it } from 'vitest'
import { printGateMessage, toastForPrintResult } from './printToast.js'

describe('print toast outcomes', () => {
  it('maps printed, already printed, uncertain, and plain errors', () => {
    expect(toastForPrintResult({ ok: true, body: { status: 'printed', message: 'Print command completed.' } })).toBe(
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
            'Print command failed or timed out. Check the printer before requesting another copy; some paper may have printed.',
        },
      }),
    ).toMatch(/uncertain|Check the printer/)
    expect(toastForPrintResult({ ok: false, error: 'Print receiver token is not set.' })).toBe(
      'Print receiver token is not set.',
    )
  })

  it('gates the Print button before calling the plugin', () => {
    expect(printGateMessage({ onMeals: false, printerOn: true, plan: { weekStart: '2026-10-17' } })).toBe(
      'Print the slip from Meals.',
    )
    expect(printGateMessage({ onMeals: true, printerOn: false, plan: { weekStart: '2026-10-17' } })).toBe(
      'The printer plugin is off.',
    )
    expect(printGateMessage({ onMeals: true, printerOn: true, plan: null })).toBe('Open a week on Meals first.')
    expect(printGateMessage({ onMeals: true, printerOn: true, plan: { weekStart: '2026-10-17' } })).toBe(null)
  })
})
