/** Map a printer plugin action result into a short toast or inline note. */

export function printGateMessage({ onMeals, printerOn, plan }) {
  if (!onMeals) return 'Print the slip from Meals.'
  if (!printerOn) return 'The printer plugin is off.'
  if (!plan?.weekStart) return 'Open a week on Meals first.'
  return null
}

export function toastForPrintResult(result) {
  if (!result || result.ok === false) {
    return String(result?.error || 'Print failed.').trim() || 'Print failed.'
  }
  const body = result.body || result
  const status = String(body?.status || '')
  const message = String(body?.message || '').trim()
  if (message === 'No additional print sent.' || /^already printed\.?$/i.test(message)) {
    return 'Already printed.'
  }
  if (status === 'printed') return 'Printed.'
  if (status === 'uncertain') {
    return message || 'Print outcome is uncertain.'
  }
  return message || (status ? status.charAt(0).toUpperCase() + status.slice(1) + '.' : 'Print finished.')
}
