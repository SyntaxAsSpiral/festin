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

    function onDown(event) {
      if (event.pointerType !== 'touch') return
      if (!window.matchMedia(NARROW_QUERY).matches) return
      if (
        !shouldBeginPull({
          pointerType: event.pointerType,
          narrow: true,
          target: event.target,
          root,
        })
      ) {
        return
      }
      clearSpring()
      gesture.current = {
        id: event.pointerId,
        y0: event.clientY,
        dy: 0,
        tracking: false,
      }
    }

    function onMove(event) {
      const g = gesture.current
      if (!g || event.pointerId !== g.id) return
      const dy = event.clientY - g.y0
      if (!g.tracking) {
        if (dy < ARM_PX) return
        // Re-check: a nested scroller may have moved, or the finger slid onto chat.
        if (
          !shouldBeginPull({
            pointerType: event.pointerType,
            narrow: window.matchMedia(NARROW_QUERY).matches,
            target: event.target,
            root,
          })
        ) {
          gesture.current = null
          return
        }
        g.tracking = true
        try {
          root.setPointerCapture(event.pointerId)
        } catch {
          /* capture is best-effort */
        }
      }
      if (dy <= 0) {
        g.dy = 0
        setVisual(0)
        setReady(false)
        return
      }
      if (event.cancelable) event.preventDefault()
      g.dy = dy
      setVisual(resistPull(dy))
      setReady(pastThreshold(dy))
    }

    function onUp(event) {
      const g = gesture.current
      if (!g || event.pointerId !== g.id) return
      gesture.current = null
      try {
        if (root.hasPointerCapture?.(event.pointerId)) root.releasePointerCapture(event.pointerId)
      } catch {
        /* ignore */
      }
      if (!g.tracking) {
        resetVisual(false)
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

    root.addEventListener('pointerdown', onDown)
    root.addEventListener('pointermove', onMove, { passive: false })
    root.addEventListener('pointerup', onUp)
    root.addEventListener('pointercancel', onUp)
    return () => {
      clearSpring()
      root.removeEventListener('pointerdown', onDown)
      root.removeEventListener('pointermove', onMove)
      root.removeEventListener('pointerup', onUp)
      root.removeEventListener('pointercancel', onUp)
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
