import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { motion } from 'motion/react'
import nameplate from './babette-nameplate.png'
import { transition } from '../motion.js'
import { useReducedMotion } from '../useReducedMotion.js'
import './surface.css'

const NARROW = '(max-width: 900px)'
const STRIP = 52
const Ctx = createContext(null)

function viewportBox() {
  const vv = window.visualViewport
  const height = vv?.height || window.innerHeight
  const overlap = vv ? Math.max(0, window.innerHeight - vv.height - vv.offsetTop) : 0
  return { height, keyboard: overlap > 80 ? overlap : 0 }
}

function clamp(n, lo, hi) {
  return Math.min(hi, Math.max(lo, n))
}

// On a wide screen the Meals pane (frieze, slip, Log) ends about here; what lies
// to its right is free. With room for her, Babette starts open and fills it.
const MEALS_EDGE = 1610
const ROOMY_MIN = 600

function roomToTheRight() {
  if (window.matchMedia(NARROW).matches) return 0
  const free = window.innerWidth - MEALS_EDGE
  return free >= ROOMY_MIN ? Math.min(free, 1600) : 0
}

export function SurfaceProvider({ children }) {
  const [state, setState] = useState(() => (roomToTheRight() ? 'peek' : 'tucked'))
  const [narrow, setNarrow] = useState(() => window.matchMedia(NARROW).matches)
  const [peekPx, setPeekPx] = useState(null)
  const [width, setWidth] = useState(() => roomToTheRight() || 420)

  useEffect(() => {
    const mq = window.matchMedia(NARROW)
    const apply = () => {
      const next = mq.matches
      setNarrow(next)
      if (!next) setState((current) => (current === 'full' ? 'peek' : current))
    }
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])

  const open = useCallback(() => setState('peek'), [])
  const tuck = useCallback(() => setState('tucked'), [])
  const expand = useCallback(() => {
    setState((current) => {
      if (!window.matchMedia(NARROW).matches) return current === 'tucked' ? 'peek' : 'peek'
      return 'full'
    })
  }, [])

  const value = {
    state,
    open,
    tuck,
    expand,
    narrow,
    peekPx,
    setPeekPx,
    width,
    setWidth,
    setState,
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useSurface() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useSurface must be used within Surface')
  return { state: ctx.state, open: ctx.open, tuck: ctx.tuck, expand: ctx.expand }
}

function useBox() {
  const [box, setBox] = useState(viewportBox)
  useEffect(() => {
    const vv = window.visualViewport
    const fit = () => setBox(viewportBox())
    fit()
    window.addEventListener('resize', fit)
    vv?.addEventListener('resize', fit)
    vv?.addEventListener('scroll', fit)
    return () => {
      window.removeEventListener('resize', fit)
      vv?.removeEventListener('resize', fit)
      vv?.removeEventListener('scroll', fit)
    }
  }, [])
  return box
}

function SurfaceView({ peekLine, lookingAt, header, children }) {
  const api = useContext(Ctx)
  const reduced = useReducedMotion()
  const { height: viewH, keyboard } = useBox()
  const panelRef = useRef(null)
  const drag = useRef({ y: 0, h: 0, moved: false })
  const widthDrag = useRef(420)
  const [liveH, setLiveH] = useState(null)
  const [liveW, setLiveW] = useState(null)

  const { state, narrow, peekPx, width, setPeekPx, setWidth, setState, open, tuck } = api
  const fullPx = viewH * 0.94
  const peekDefault = viewH * 0.46
  const openH = state === 'full' ? fullPx : (peekPx ?? peekDefault)
  const shownH = liveH ?? (state === 'tucked' ? STRIP : openH)
  const shownW = liveW ?? width
  // Ultrawide: Meals sits left, so the overlay may be pulled far into the free space.
  const maxW = window.innerWidth >= 1800 ? Math.min(1600, window.innerWidth - 900) : Math.min(720, window.innerWidth - 160)

  // On desktop the open panel takes the right of the window; an open card moves
  // over into the space left of it (--chat-cover) instead of being covered.
  const cover = !narrow && state !== 'tucked' ? clamp(shownW, 340, maxW) : 0
  useEffect(() => {
    document.documentElement.style.setProperty('--chat-cover', cover + 'px')
  }, [cover])
  useEffect(() => () => document.documentElement.style.removeProperty('--chat-cover'), [])

  useEffect(() => {
    function onKey(event) {
      if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return
      const typing = event.target?.closest?.('input, textarea, select, [contenteditable="true"]')
      if (event.key === 'Escape') {
        if (typing || state === 'tucked') return
        // Confirm, Card, then Settings close first (state-machine.md §2.5 / §5).
        if (document.getElementById('sidebar')?.classList.contains('open')) return
        if (document.querySelector('.card-layer .card, .confirm')) return
        event.preventDefault()
        tuck()
        return
      }
      if (event.key.toLowerCase() !== 'b' || typing) return
      event.preventDefault()
      if (state === 'tucked') open()
      else tuck()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [state, open, tuck])

  useEffect(() => {
    if (narrow || state === 'tucked') return undefined
    function onPointerDown(event) {
      const el = event.target
      if (!(el instanceof Element)) return
      if (el.closest('.surface-panel, .surface-rail, [data-settings], #sidebar, #gear, [data-card], #recipe, .card')) return
      tuck()
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [narrow, state, tuck])

  useEffect(() => {
    if (state === 'tucked') return undefined
    const field = panelRef.current?.querySelector('textarea, input')
    field?.focus({ preventScroll: true })
    return undefined
  }, [state])

  function finishHeight(next) {
    setLiveH(null)
    if (next < viewH * 0.2) {
      tuck()
      return
    }
    if (next > viewH * 0.78) {
      setState('full')
      return
    }
    setPeekPx(clamp(next, STRIP, fullPx))
    setState('peek')
  }

  const looking = lookingAt ? 'looking at ' + lookingAt : ''

  return (
    <div className="surface-slot" data-state={state} data-layout={narrow ? 'drawer' : 'rail'}>
      {narrow ? null : (
        <button
          type="button"
          className="surface-rail"
          aria-expanded={state !== 'tucked'}
          aria-controls="bab"
          onClick={() => (state === 'tucked' ? open() : tuck())}
        >
          <img src="/art/chrome/b-glyph-112.png" alt="" draggable={false} />
          <span>Babette</span>
        </button>
      )}
      <motion.section
        id="bab"
        ref={panelRef}
        className="surface-panel"
        data-state={state}
        data-layout={narrow ? 'drawer' : 'rail'}
        aria-label="Babette"
        initial={false}
        animate={
          narrow
            ? { height: shownH, x: 0 }
            : { height: '100%', x: state === 'tucked' ? 'calc(100% + 24px)' : 0 }
        }
        transition={liveH != null || keyboard || reduced ? { duration: 0 } : transition(reduced, 'drawer')}
        style={narrow ? { bottom: keyboard } : { width: clamp(shownW, 340, maxW) }}
      >
        {!narrow && state !== 'tucked' && (
          <motion.div
            className="surface-width"
            aria-label="Resize chat"
            role="separator"
            drag="x"
            dragConstraints={{ left: 0, right: 0 }}
            dragElastic={0}
            dragMomentum={false}
            dragSnapToOrigin
            onDragStart={(event, info) => {
              widthDrag.current = { x: info.point.x, w: shownW, live: shownW }
            }}
            onDrag={(event, info) => {
              const origin = widthDrag.current
              const next = clamp(origin.w - (info.point.x - origin.x), 340, maxW)
              origin.live = next
              setLiveW(next)
            }}
            onDragEnd={() => {
              const next = widthDrag.current?.live ?? width
              setWidth(clamp(next, 340, maxW))
              setLiveW(null)
            }}
          />
        )}
        <motion.header
          className="surface-head"
          drag={narrow ? 'y' : false}
          dragConstraints={{ top: 0, bottom: 0 }}
          dragElastic={0}
          dragMomentum={false}
          dragSnapToOrigin
          onPointerDown={() => {
            drag.current.suppressTap = false
          }}
          onDragStart={(event, info) => {
            drag.current = { y: info.point.y, h: shownH, live: shownH, moved: false, suppressTap: false }
          }}
          onDrag={(event, info) => {
            if (!narrow) return
            const next = clamp(drag.current.h - (info.point.y - drag.current.y), STRIP, fullPx)
            if (Math.abs(info.point.y - drag.current.y) > 4) drag.current.moved = true
            drag.current.live = next
            setLiveH(next)
          }}
          onDragEnd={() => {
            if (!narrow) return
            const moved = drag.current.moved
            const live = drag.current.live
            drag.current.moved = false
            if (!moved) {
              setLiveH(null)
              return
            }
            drag.current.suppressTap = true
            finishHeight(live ?? drag.current.h)
          }}
          onClick={(event) => {
            if (!narrow) return
            if (drag.current.suppressTap) {
              drag.current.suppressTap = false
              return
            }
            const el = event.target
            if (el instanceof Element && el.closest('button, a, input, textarea')) return
            if (state === 'tucked') open()
            else tuck()
          }}
        >
          {narrow && <span className="surface-grip" aria-hidden="true" />}
          <img className="surface-name" src={nameplate} alt="Babette" draggable={false} />
          {looking && <span className="surface-look" id="lk">{looking}</span>}
          {state === 'tucked' && peekLine ? <span className="surface-peek" id="peek">{peekLine}</span> : null}
          <span className="surface-gap" />
          {state !== 'tucked' && header ? <span className="surface-model">{header}</span> : null}
          {state !== 'tucked' && (
            <button type="button" className="surface-close" aria-label="Close chat" title="Close" onClick={tuck}>×</button>
          )}
        </motion.header>
        <div className="surface-body" hidden={state === 'tucked' ? true : undefined}>
          {children}
        </div>
      </motion.section>
    </div>
  )
}

export default function Surface(props) {
  const ctx = useContext(Ctx)
  if (!ctx) {
    return (
      <SurfaceProvider>
        <SurfaceView {...props} />
      </SurfaceProvider>
    )
  }
  return <SurfaceView {...props} />
}
