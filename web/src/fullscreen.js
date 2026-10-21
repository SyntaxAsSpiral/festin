// The browser drops full screen whenever the page is hidden (another app, the screen
// sleeping) and will only enter it again from a tap. So the wish for full screen is
// remembered, and the next tap restores it. Only a person leaving it while looking at
// the page forgets the wish.
const KEY = 'festin.fullscreen'
export const HIDE_WINDOW_MS = 2000

export function wantsFullscreen(store = globalThis.localStorage) {
  try {
    return store.getItem(KEY) === '1'
  } catch {
    return false
  }
}

export function setWantsFullscreen(on, store = globalThis.localStorage) {
  try {
    if (on) store.setItem(KEY, '1')
    else store.removeItem(KEY)
  } catch {
    /* storage unavailable: the wish just lasts one visit */
  }
}

// Full screen ended at exitAt. It was the person's doing unless the page is hidden now, or
// was hidden within the window either side of the exit (the two events arrive in either order).
export function exitWasUser({ hidden, hiddenAt, exitAt }) {
  if (hidden) return false
  if (hiddenAt == null) return true
  return Math.abs(exitAt - hiddenAt) > HIDE_WINDOW_MS
}
