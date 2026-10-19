/** Map a printer plugin action result into a short toast or inline note. */

/**
 * What the Print button prints: the open recipe card, else the week on Meals.
 * Returns { message } when there is nothing to print, else { action, body }.
 */
export function printTarget({ onMeals, card, printerOn, plan }) {
  if (!printerOn) return { message: 'The printer plugin is off.' }
  if (card?.kind === 'recipes' && card.id) return { action: 'print-recipe', body: { recipe_id: card.id }, sending: 'Sending the recipe to the printer…' }
  if (card) return { message: 'Only recipes and the week’s slip print from here.' }
  if (!onMeals) return { message: 'Open a recipe, or the week on Meals, to print.' }
  if (!plan?.weekStart) return { message: 'Open a week on Meals first.' }
  return { action: 'print-dinner', body: { weekStart: plan.weekStart, plan }, sending: 'Sending the slip to the printer…' }
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
