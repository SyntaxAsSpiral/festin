import { useEffect, useRef, useState } from 'react'
import {
  ARM_PX,
  NARROW_QUERY,
  defaultReload,
  pastThreshold,
  releaseAction,
  resistPull,
  shouldBeginPull,
} from './pullRefresh.js'

/**
 * Quiet pull-to-refresh for narrow touch layouts. Listens on `root` (the
 * stage element). Shows a paper-toned "Release to refresh" line that tracks
 * the finger with resistance; reloads past the threshold; springs back
 * otherwise (instant hide when reduced motion is on).
 */
export function PullRefresh({ root, reduced = false, reload = defaultReload }) {
  const [visual, setVisual] = useState(0)
  const [ready, setReady] = useState(false)
  const [spring, setSpring] = useState(false)
  const gesture = useRef(null)
  const springTimer = useRef(0)

  useEffect(() => {
    if (!root) return undefined

    function clearSpring() {
      if (springTimer.current) {
        window.clearTimeout(springTimer.current)
        springTimer.current = 0
      }
      setSpring(false)
    }

    function resetVisual(withSpring) {
      if (withSpring && !reduced) {
        setSpring(true)
        setVisual(0)
        setReady(false)
        springTimer.current = window.setTimeout(() => setSpring(false), 280)
        return
      }
      clearSpring()
      setVisual(0)
      setReady(false)
    }

    // Touch events, not pointer events: the stage pans vertically, so the browser
    // claims a downward drag and sends pointercancel before the pull can arm. Only
    // a non-passive touchmove may preventDefault and keep the gesture ours.
    function onStart(event) {
      if (event.touches.length !== 1) return
      if (!window.matchMedia(NARROW_QUERY).matches) return
      if (!shouldBeginPull({ pointerType: 'touch', narrow: true, target: event.target, root })) return
      clearSpring()
      const t = event.touches[0]
      gesture.current = { id: t.identifier, y0: t.clientY, dy: 0, tracking: false }
    }

    function onMove(event) {
      const g = gesture.current
      if (!g) return
      const t = Array.from(event.touches).find((touch) => touch.identifier === g.id)
      if (!t) return
      const dy = t.clientY - g.y0
      if (!g.tracking) {
        if (dy < 0) {
          // An upward drag is an ordinary scroll.
          gesture.current = null
          return
        }
        if (dy < ARM_PX) {
          if (event.cancelable) event.preventDefault()
          return
        }
        g.tracking = true
      }
      if (event.cancelable) event.preventDefault()
      g.dy = Math.max(0, dy)
      setVisual(resistPull(g.dy))
      setReady(pastThreshold(g.dy))
    }

    function onEnd(event) {
      const g = gesture.current
      if (!g) return
      if (Array.from(event.touches).some((touch) => touch.identifier === g.id)) return
      gesture.current = null
      if (!g.tracking || event.type === 'touchcancel') {
        resetVisual(g.tracking)
        return
      }
      if (releaseAction(g.dy) === 'reload') {
        reload()
        // Real reload tears the page down; a test stub leaves us here, so tuck away.
        resetVisual(false)
        return
      }
      resetVisual(true)
    }

    root.addEventListener('touchstart', onStart, { passive: true })
    root.addEventListener('touchmove', onMove, { passive: false })
    root.addEventListener('touchend', onEnd)
    root.addEventListener('touchcancel', onEnd)
    return () => {
      clearSpring()
      root.removeEventListener('touchstart', onStart)
      root.removeEventListener('touchmove', onMove)
      root.removeEventListener('touchend', onEnd)
      root.removeEventListener('touchcancel', onEnd)
    }
  }, [root, reduced, reload])

  const show = visual > 0 || spring
  if (!show) return null

  return (
    <div
      className={'pull-refresh' + (ready ? ' ready' : '') + (spring ? ' spring' : '')}
      style={{ height: visual }}
      data-pull={visual}
      data-ready={ready ? '1' : '0'}
      role="status"
      aria-live="polite"
    >
      <span className="pull-refresh-line">{ready ? 'Release to refresh' : ''}</span>
    </div>
  )
}
