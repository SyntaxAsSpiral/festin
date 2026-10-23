import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { rememberOrigin } from '../cards/origin.js'
import { plateFor } from '../cards/kinds.js'
import { useReducedMotion } from '../useReducedMotion.js'
import { DISH_DROP } from './activePlan.js'
import { flingVelocity, spinStep } from './fling.js'
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
const DRIFT = 20 // px/s, the column's own pace
const AXIS = 6 // px before a press is read as a scroll or a pull
const CATCH = 150 // px/s; a press on a spin this fast only stops it

// A dish pulled out of the frieze: a copy of its tile follows the pointer, lights the
// night under it, and on release hands the dish to that night.
function startLift(btn, e) {
  const r = btn.getBoundingClientRect()
  const ghost = document.createElement('div')
  ghost.className = 'frieze frieze-ghost'
  ghost.style.width = r.width + 'px'
  ghost.appendChild(btn.cloneNode(true))
  document.body.appendChild(ghost)
  const gx = e.clientX - r.left
  const gy = e.clientY - r.top
  let over = null
  const nightAt = (x, y) => document.elementFromPoint(x, y)?.closest?.('.slip .row[data-night]') || null
  return {
    move(x, y) {
      ghost.style.transform = `translate(${x - gx}px, ${y - gy}px) rotate(-2deg)`
      const row = nightAt(x, y)
      if (row !== over) {
        over?.classList.remove('drop-over')
        row?.classList.add('drop-over')
        over = row
      }
    },
    drop(at) {
      over?.classList.remove('drop-over')
      ghost.remove()
      const row = at && nightAt(at.x, at.y)
      if (row) {
        row.dispatchEvent(
          new CustomEvent(DISH_DROP, {
            bubbles: true,
            detail: { night: Number(row.dataset.night), id: btn.dataset.id, title: btn.dataset.title },
          }),
        )
      }
    },
  }
}

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

// Looping recipe column: auto-scroll, hold on hover/drag/wheel, flick to spin, pull a
// dish sideways onto a night of the slip, tap opens Recipes.
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
  const spin = useRef(0)
  const samples = useRef([])
  const tile = useRef(null)
  const lift = useRef(null)
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
      const dt = Math.min((t - last.current) / 1000, 0.1)
      last.current = t
      if (wq.current) {
        const m = Math.abs(wq.current) < 0.5 ? wq.current : wq.current * (1 - Math.exp(-dt * 16))
        off.current += m
        wq.current -= m
      }
      // The spin carries a flick on and eases into the drift (held: toward rest).
      if (drag.current == null) {
        const held = hover.current || t <= wheelHold.current
        spin.current = spinStep(spin.current, held ? 0 : DRIFT, dt)
        off.current += spin.current * dt
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
      if (!lift.current) drag.current = null
    }
    let idle = 0
    const onDown = (e) => {
      // A press catches the wheel; catching a real spin is not a tap on a dish.
      moved.current = Math.abs(spin.current) > CATCH
      spin.current = 0
      wq.current = 0
      drag.current = { x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY, mode: null }
      samples.current = [{ t: e.timeStamp, off: off.current }]
      tile.current = e.target.closest?.('button.tile') || null
      hover.current = true
    }
    const onMove = (e) => {
      const d = drag.current
      if (d == null) return
      if (!d.mode) {
        const dx = e.clientX - d.x0
        const dy = e.clientY - d.y0
        if (Math.hypot(dx, dy) < AXIS) return
        // Mostly sideways, off a dish: pull it toward the slip. Else scroll.
        d.mode = tile.current && Math.abs(dx) > Math.abs(dy) ? 'lift' : 'scroll'
        moved.current = true
        // Capture only once it is really a drag: capturing on press would send the
        // release (and so the click) to the frieze instead of the dish tapped.
        try {
          fr.setPointerCapture(e.pointerId)
        } catch {
          /* ignore */
        }
        if (d.mode === 'lift') lift.current = startLift(tile.current, e)
      }
      if (d.mode === 'lift') {
        lift.current?.move(e.clientX, e.clientY)
      } else {
        off.current += d.y - e.clientY
        samples.current.push({ t: e.timeStamp, off: off.current })
        if (samples.current.length > 12) samples.current.shift()
      }
      d.x = e.clientX
      d.y = e.clientY
    }
    const onUp = (e) => {
      const d = drag.current
      drag.current = null
      if (lift.current) {
        lift.current.drop(e.type === 'pointerup' ? { x: e.clientX, y: e.clientY } : null)
        lift.current = null
      } else if (d?.mode === 'scroll' && e.type === 'pointerup') {
        spin.current = flingVelocity(samples.current, e.timeStamp)
      }
      if (e.pointerType !== 'mouse') {
        clearTimeout(idle)
        idle = window.setTimeout(() => {
          hover.current = false
        }, 2500)
      }
    }
    const onWheel = (e) => {
      e.preventDefault()
      spin.current = 0
      wq.current += e.deltaY || e.deltaX
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
      lift.current?.drop(null)
      lift.current = null
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
              data-id={it.id}
              data-title={it.n}
              onClick={(e) => openRecipe(it, e.currentTarget)}
            >
              <span className="plate">
                <img src={plateFor(it.p)} alt="" draggable={false} />
              </span>
              <b>{it.n}</b>
            </button>
          ),
        )}
      </div>
    </div>
  )
}
