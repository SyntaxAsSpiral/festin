/** The Meals slip week currently on screen — Print reads this. */

let active = null

export function setActiveMealsPlan(plan) {
  active = plan && typeof plan === 'object' ? plan : null
}

export function getActiveMealsPlan() {
  return active
}
