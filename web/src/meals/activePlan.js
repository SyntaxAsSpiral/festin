/** The Meals slip week currently on screen — Print reads this. */

let active = null

export function setActiveMealsPlan(plan) {
  active = plan && typeof plan === 'object' ? plan : null
}

export function getActiveMealsPlan() {
  return active
}

/** A frieze dish dropped on a night of the slip: detail { night, id, title }. */
export const DISH_DROP = 'festin:dish-drop'
