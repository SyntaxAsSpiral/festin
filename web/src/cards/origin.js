// Where the open card came from, so it can flip out of that spot and back into it.
let origin = null

export function rememberOrigin(el) {
  const rect = el?.getBoundingClientRect?.()
  origin = rect ? { el, rect } : null
}

// The rect to flip from, or null when the origin is gone or off-screen (fade instead).
export function originRect() {
  if (!origin) return null
  const rect = origin.el?.isConnected ? origin.el.getBoundingClientRect() : origin.rect
  const onScreen = rect.bottom > 0 && rect.top < window.innerHeight && rect.width > 0
  return onScreen ? rect : null
}

export function forgetOrigin() {
  origin = null
}
