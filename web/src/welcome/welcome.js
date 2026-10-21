// The welcome shows once per device; a device that has seen it keeps the flag.
const KEY = 'festin.welcomed'

export function hasSeenWelcome(store = globalThis.localStorage) {
  try {
    return store.getItem(KEY) === '1'
  } catch {
    // Storage is blocked: show it once per visit rather than every render.
    return false
  }
}

export function markWelcomeSeen(store = globalThis.localStorage) {
  try {
    store.setItem(KEY, '1')
  } catch {
    /* blocked: it shows again next visit */
  }
}

// Settings can ask for the welcome again; the dialog listens for this event.
export const WELCOME_EVENT = 'festin:welcome'

export function showWelcome(target = globalThis.window) {
  target?.dispatchEvent(new Event(WELCOME_EVENT))
}
