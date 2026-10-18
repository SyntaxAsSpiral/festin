import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { rememberOrigin } from '../cards/origin.js'
import { plateFor } from '../cards/kinds.js'
import { useReducedMotion } from '../useReducedMotion.js'
import { fetchRecipes } from './plan.js'

const MOTIFS = [
  '/art/frieze/motif-scroll.png',
  '/art/frieze/motif-rose.png',
  '/art/frieze/motif-wheat.png',
  '/art/frieze/motif-blossom.png',
  '/art/frieze/motif-sage.png',
  '/art/frieze/motif-acanthus.png',
]

function buildItems(recipes) {
  const items = []
  recipes.forEach((r, i) => {
    if (i % 5 === 0) {
      items.push({ t: 'orn', o: items.filter((x) => x.t === 'orn').length })
    }
    items.push({
      t: 'r',
      id: r.id,
      n: r.title || r.id,
      p: r.category || 'uncategorized',
      tip: r.searchDescription || '',
    })
  })
  return items
}

// Looping recipe column: auto-scroll, hold on hover/drag/wheel, tap opens Recipes.
export function Frieze() {
  const navigate = useNavigate()
  const reduced = useReducedMotion()
  const trackRef = useRef(null)
  const wrapRef = useRef(null)
  const off = useRef(0)
  const hover = useRef(false)
  const drag = useRef(null)
  const moved = useRef(false)
  const wheelHold = useRef(0)
  const wq = useRef(0)
  const last = useRef(performance.now())
  const [recipes, setRecipes] = useState([])
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let gone = false
    fetchRecipes(80)
      .then((list) => !gone && setRecipes(list))
      .catch(() => !gone && setRecipes([]))
    return () => {
      gone = true
    }
  }, [])

  const items = useMemo(() => buildItems(recipes || []), [recipes])
  const loop = useMemo(() => (items.length ? [...items, ...items] : []), [items])

  useEffect(() => {
    setReady(Boolean(items.length))
  }, [items.length])

  useEffect(() => {
    if (!ready || reduced) return undefined
    let raf = 0
    const tick = (t) => {
      const dt = (t - last.current) / 1000
      last.current = t
      if (wq.current) {
        const m = Math.abs(wq.current) < 0.5 ? wq.current : wq.current * (1 - Math.exp(-Math.min(dt, 0.1) * 16))
        off.current += m
        wq.current -= m
      }
      if (!hover.current && drag.current == null && t > wheelHold.current) {
        off.current += 20 * dt
      }
      const track = trackRef.current
      if (track) {
        const half = track.scrollHeight / 2
        if (half > 0) {
          off.current = ((off.current % half) + half) % half
          track.style.transform = `translateY(${-off.current}px)`
        }
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [ready, reduced])

  useEffect(() => {
    const fr = wrapRef.current
    if (!fr) return undefined

    const onEnter = () => {
      hover.current = true
    }
    const onLeave = () => {
      hover.current = false
      drag.current = null
    }
    let idle = 0
    const onDown = (e) => {
      drag.current = e.clientY
      moved.current = false
      hover.current = true
      try {
        fr.setPointerCapture(e.pointerId)
      } catch {
        /* ignore */
      }
    }
    const onMove = (e) => {
      if (drag.current == null) return
      const dy = drag.current - e.clientY
      if (Math.abs(dy) > 2) moved.current = true
      off.current += dy
      drag.current = e.clientY
    }
    const onUp = (e) => {
      drag.current = null
      if (e.pointerType !== 'mouse') {
        clearTimeout(idle)
        idle = window.setTimeout(() => {
          hover.current = false
        }, 2500)
      }
    }
    const onWheel = (e) => {
      e.preventDefault()
      const u = 1
      wq.current += (e.deltaY || e.deltaX) * u
      wheelHold.current = performance.now() + 2500
      hover.current = true
    }

    fr.addEventListener('pointerenter', onEnter)
    fr.addEventListener('pointerleave', onLeave)
    fr.addEventListener('pointerdown', onDown)
    fr.addEventListener('pointermove', onMove)
    fr.addEventListener('pointerup', onUp)
    fr.addEventListener('pointercancel', onUp)
    fr.addEventListener('wheel', onWheel, { passive: false })
    return () => {
      clearTimeout(idle)
      fr.removeEventListener('pointerenter', onEnter)
      fr.removeEventListener('pointerleave', onLeave)
      fr.removeEventListener('pointerdown', onDown)
      fr.removeEventListener('pointermove', onMove)
      fr.removeEventListener('pointerup', onUp)
      fr.removeEventListener('pointercancel', onUp)
      fr.removeEventListener('wheel', onWheel)
    }
  }, [ready])

  function openRecipe(item, el) {
    if (moved.current) return
    rememberOrigin(el)
    navigate('/recipes/' + encodeURIComponent(item.id))
  }

  if (!items.length) {
    return null
  }

  return (
    <div className="frieze-body" ref={wrapRef} style={{ height: '100%', overflow: 'hidden' }}>
      <div className="track" ref={trackRef}>
        {loop.map((it, i) =>
          it.t === 'orn' ? (
            <div key={'orn-' + i} className="tile orn" aria-hidden="true">
              <img className="sh" src={MOTIFS[it.o % MOTIFS.length]} alt="" draggable={false} />
            </div>
          ) : (
            <button
              key={it.id + '-' + i}
              type="button"
              className="tile"
              onClick={(e) => openRecipe(it, e.currentTarget)}
            >
              <img src={plateFor(it.p)} alt="" draggable={false} />
              <b>{it.n}</b>
              <i>{20 + it.n.length}m</i>
              {it.tip ? <span className="ds">{it.tip}</span> : null}
            </button>
          ),
        )}
      </div>
    </div>
  )
}
