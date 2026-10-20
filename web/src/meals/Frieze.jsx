import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { rememberOrigin } from '../cards/origin.js'
import { plateFor } from '../cards/kinds.js'
import { useReducedMotion } from '../useReducedMotion.js'
import { fetchRecipeSample } from './plan.js'

const MOTIFS = [
  '/art/frieze/motif-scroll.png',
  '/art/frieze/motif-rose.png',
  '/art/frieze/motif-wheat.png',
  '/art/frieze/motif-blossom.png',
  '/art/frieze/motif-sage.png',
  '/art/frieze/motif-acanthus.png',
]

// The frieze is a meal in five courses; each group of five, between ornaments,
// runs soup, salad, main, a snack or side, then dessert. Each course is its own
// random draw, so every visit is a new spread.
const COURSES = [
  ['soups-stews'],
  ['salads-sides'],
  ['casseroles', 'chicken', 'meats', 'fish-seafood', 'pasta', 'eggs-breakfast'],
  ['snacks-sandwiches', 'pantry-party', 'breads', 'pickles-preserves', 'sauces-dressings', 'seasonings', 'drinks', 'misc'],
  ['sweets', 'cakes', 'cookies', 'pies-tarts'],
]
const MEALS = 16

// Deal course draws into meals: soup, salad, main, side, dessert, then the next meal.
export function courseOrder(draws) {
  const meals = Math.min(...draws.map((d) => d.length))
  const out = []
  for (let m = 0; m < meals; m++) draws.forEach((d) => out.push(d[m]))
  return out
}

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
    // Queued dishes lead the frieze (oldest first); course draws fill the rest.
    Promise.all([
      fetch('/api/recipes?queued=1&limit=40', { headers: { Accept: 'application/json' } })
        .then((res) => (res.ok ? res.json() : { recipes: [] }))
        .then((body) => body.recipes || [])
        .catch(() => []),
      ...COURSES.map((cats) => fetchRecipeSample(MEALS, cats)),
    ])
      .then(([queued, ...draws]) => {
        if (gone) return
        const lead = queued || []
        const seen = new Set(lead.map((r) => r.id))
        const rest = courseOrder(draws).filter((r) => !seen.has(r.id))
        setRecipes([...lead, ...rest])
      })
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
    }
    const onMove = (e) => {
      if (drag.current == null) return
      const dy = drag.current - e.clientY
      // Capture only once it is really a drag: capturing on press would send the
      // release (and so the click) to the frieze instead of the dish tapped.
      if (Math.abs(dy) > 2 && !moved.current) {
        moved.current = true
        try {
          fr.setPointerCapture(e.pointerId)
        } catch {
          /* ignore */
        }
      }
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
            </button>
          ),
        )}
      </div>
    </div>
  )
}
