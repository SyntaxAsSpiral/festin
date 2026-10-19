// Pull-to-refresh for the fixed-height shell: the document never scrolls, so the
// browser's native gesture never engages (and Fullscreen API turns it off).

export const THRESHOLD_PX = 80
export const NARROW_QUERY = '(max-width: 900px)'
export const ARM_PX = 8

/** Finger travel → visible pull, with growing resistance. */
export function resistPull(dy) {
  if (!(dy > 0)) return 0
  return Math.round((dy * 180) / (dy + 180))
}

export function pastThreshold(fingerDy) {
  return fingerDy >= THRESHOLD_PX
}

export function releaseAction(fingerDy) {
  return pastThreshold(fingerDy) ? 'reload' : 'cancel'
}

export function isTypingTarget(el) {
  if (!el || typeof el.closest !== 'function') return false
  return Boolean(el.closest('input, textarea, select, [contenteditable="true"]'))
}

/** Chat drawer, open card, or settings — never steal their gestures. */
export function isBlockedRegion(el) {
  if (!el || typeof el.closest !== 'function') return false
  return Boolean(el.closest('.surface-slot, .surface-panel, .card-layer, .card, #sidebar'))
}

export function canScrollY(el) {
  if (!el) return false
  if (typeof document !== 'undefined' && (el === document.body || el === document.documentElement)) {
    return false
  }
  const style = typeof window !== 'undefined' ? window.getComputedStyle(el) : null
  if (!style) return false
  const oy = style.overflowY
  if (oy !== 'auto' && oy !== 'scroll' && oy !== 'overlay') return false
  return el.scrollHeight > el.clientHeight + 1
}

/** Nearest vertical scroller under the finger, stopping at root. */
export function scrollParentUnder(el, stopAt) {
  const isEl =
    el &&
    typeof el === 'object' &&
    (typeof Element === 'undefined' ? typeof el.closest === 'function' : el instanceof Element)
  let node = isEl ? el : null
  const doc = typeof document !== 'undefined' ? document : null
  while (node && node !== stopAt && node !== doc?.documentElement && node !== doc?.body) {
    if (canScrollY(node)) return node
    node = node.parentElement
  }
  if (stopAt && canScrollY(stopAt)) return stopAt
  return null
}

export function atTop(el) {
  return !el || el.scrollTop <= 0
}

export function isNarrowLayout(matchMedia = typeof window !== 'undefined' ? window.matchMedia.bind(window) : null) {
  if (!matchMedia) return false
  return matchMedia(NARROW_QUERY).matches
}

/**
 * Whether a pointerdown may start a pull gesture.
 * Only touch on the narrow layout; never over chat/card/settings/inputs;
 * only when every scroll parent under the finger is already at its top.
 */
export function shouldBeginPull({ pointerType, narrow, target, root }) {
  if (pointerType !== 'touch') return false
  if (!narrow) return false
  if (isTypingTarget(target)) return false
  if (isBlockedRegion(target)) return false
  const scroller = scrollParentUnder(target, root)
  if (scroller && !atTop(scroller)) return false
  return true
}

/** Test hook: Playwright can set window.__festinPullReload to avoid a real reload. */
export function defaultReload() {
  if (typeof window !== 'undefined' && typeof window.__festinPullReload === 'function') {
    window.__festinPullReload()
    return
  }
  window.location.reload()
}
