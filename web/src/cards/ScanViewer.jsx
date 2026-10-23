import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useReducedMotion } from '../useReducedMotion.js'
import { fitView, isFitted, panBy, rotateView, zoomAt } from './zoom.js'

const STEP = 1.5
const TAP_MS = 300

// A photo or box scan over the whole app: opens fitted, zooms (pinch, wheel, double
// tap or click, buttons) and pans (drag) without ever closing itself, turns a quarter at
// a time about the middle of the view. Scans can be replaced or deleted from here;
// the card's own Edit and Delete are covered while it is open.
export function ScanViewer({ src, alt, onClose, onReplace, onDelete }) {
  const reduced = useReducedMotion()
  const stage = useRef(null)
  const file = useRef(null)
  const [img, setImg] = useState(null)
  const [box, setBox] = useState(null)
  const [view, setView] = useState(null)
  const [eased, setEased] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const pointers = useRef(new Map())
  const lastTap = useRef(null)
  const moved = useRef(false)
  const start = useRef(null)

  // The newest geometry, for handlers bound once.
  const live = useRef({})
  live.current = { img, box, view }

  useLayoutEffect(() => {
    const el = stage.current
    if (!el) return undefined
    const measure = () => setBox({ w: el.clientWidth, h: el.clientHeight })
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // A new image (or a new stage size while fitted) starts fitted.
  useEffect(() => {
    if (!img || !box) return
    setView((v) => (!v || v.src !== src || isFitted(v, img, box) ? { ...fitView(img, box, v?.src === src ? v.r : 0), src } : v))
  }, [img, box, src])

  function apply(next, ease = false) {
    setEased(ease && !reduced)
    setView((v) => (v ? { ...next(v), src: v.src } : v))
  }

  // Pointer position as an offset from the stage centre.
  function at(e) {
    const r = stage.current.getBoundingClientRect()
    return { x: e.clientX - r.left - r.width / 2, y: e.clientY - r.top - r.height / 2 }
  }

  const zoomBy = (k, p = { x: 0, y: 0 }, ease = true) => apply((v) => zoomAt(v, k, p.x, p.y, img, box), ease)
  const fit = () => apply((v) => fitView(img, box, v.r), true)
  const turn = () => apply((v) => rotateView(v, img, box), true)
  const toggle = (p) => {
    if (!view) return
    if (isFitted(view, img, box)) zoomBy(2.5, p)
    else fit()
  }

  useEffect(() => {
    const el = stage.current
    const onWheel = (e) => {
      e.preventDefault()
      const { img: i, box: b } = live.current
      if (!i || !b) return
      const p = at(e)
      // Trackpad pinch arrives as a wheel with ctrlKey and small deltas.
      const k = Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015))
      setEased(false)
      setView((v) => (v ? { ...zoomAt(v, k, p.x, p.y, i, b), src: v.src } : v))
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  // Keys are the viewer's while it is open; Esc closes it, not the card under it.
  useEffect(() => {
    const onKey = (e) => {
      const keys = { Escape: 1, '+': 1, '=': 1, '-': 1, r: 1, R: 1, 0: 1 }
      if (!keys[e.key] || e.target?.closest?.('input, textarea')) return
      e.preventDefault()
      e.stopImmediatePropagation()
      if (e.key === 'Escape') return confirming ? setConfirming(false) : onClose()
      if (!live.current.view) return
      if (e.key === '-') zoomBy(1 / STEP)
      else if (e.key === 'r' || e.key === 'R') turn()
      else if (e.key === '0') fit()
      else zoomBy(STEP)
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  })

  function onDown(e) {
    if (!view) return
    stage.current.setPointerCapture?.(e.pointerId)
    const p = at(e)
    pointers.current.set(e.pointerId, p)
    if (pointers.current.size === 1) {
      start.current = p
      moved.current = false
    } else {
      moved.current = true
    }
    setDragging(true)
  }

  function onMove(e) {
    const prev = pointers.current.get(e.pointerId)
    if (!prev || !view) return
    const p = at(e)
    const others = [...pointers.current.entries()].filter(([id]) => id !== e.pointerId)
    const s0 = start.current
    if (s0 && Math.hypot(p.x - s0.x, p.y - s0.y) > 6) moved.current = true
    setEased(false)
    if (others.length === 1) {
      // Pinch: scale by the change in spread about the old midpoint, then follow the midpoint.
      const o = others[0][1]
      const d0 = Math.hypot(prev.x - o.x, prev.y - o.y)
      const d1 = Math.hypot(p.x - o.x, p.y - o.y)
      const m0 = { x: (prev.x + o.x) / 2, y: (prev.y + o.y) / 2 }
      const m1 = { x: (p.x + o.x) / 2, y: (p.y + o.y) / 2 }
      setView((v) => {
        const z = d0 > 0 ? zoomAt(v, d1 / d0, m0.x, m0.y, img, box) : v
        return { ...panBy(z, m1.x - m0.x, m1.y - m0.y, img, box), src: v.src }
      })
    } else if (others.length === 0) {
      setView((v) => ({ ...panBy(v, p.x - prev.x, p.y - prev.y, img, box), src: v.src }))
    }
    pointers.current.set(e.pointerId, p)
  }

  function onUp(e) {
    const p = pointers.current.get(e.pointerId)
    pointers.current.delete(e.pointerId)
    if (!pointers.current.size) setDragging(false)
    if (!p || moved.current || e.type !== 'pointerup') return
    // Double tap or double click: in to that spot, or back to fitted.
    const t = lastTap.current
    if (t && e.timeStamp - t.at < TAP_MS && Math.hypot(p.x - t.x, p.y - t.y) < 24) {
      lastTap.current = null
      toggle(p)
    } else {
      lastTap.current = { at: e.timeStamp, x: p.x, y: p.y }
    }
  }

  async function run(work, done) {
    setBusy(true)
    setNote('')
    try {
      await work()
      done?.()
    } catch (err) {
      setNote(err.message || 'The kitchen did not save that.')
    } finally {
      setBusy(false)
    }
  }

  const style = view
    ? {
        width: img.w,
        height: img.h,
        transform: `translate(-50%, -50%) translate(${view.x}px, ${view.y}px) rotate(${view.r}deg) scale(${view.s})`,
      }
    : { visibility: 'hidden' }

  return createPortal(
    <div className="viewer" role="dialog" aria-modal="true" aria-label={alt}>
      <div
        ref={stage}
        className={'viewer-stage' + (dragging ? ' dragging' : '')}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerCancel={onUp}
      >
        <img
          className={eased ? 'eased' : undefined}
          src={src}
          alt={alt}
          draggable={false}
          style={style}
          onLoad={(e) => setImg({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
        />
      </div>
      <div className="viewer-bar" role="toolbar" aria-label="Photo">
        <button type="button" onClick={() => zoomBy(1 / STEP)} aria-label="Zoom out" data-tip="Zoom out (−)">
          −
        </button>
        <button type="button" onClick={() => zoomBy(STEP)} aria-label="Zoom in" data-tip="Zoom in (+)">
          +
        </button>
        <button type="button" onClick={fit} aria-label="Fit" data-tip="Fit (0)">
          ⤢
        </button>
        <button type="button" onClick={turn} aria-label="Rotate a quarter turn" data-tip="Rotate (R)">
          ⟳
        </button>
        {onReplace && (
          <>
            <span className="viewer-gap" />
            <button type="button" disabled={busy} onClick={() => file.current?.click()}>
              Replace
            </button>
            <input
              ref={file}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              hidden
              onChange={(e) => {
                const chosen = e.target.files?.[0]
                e.target.value = ''
                if (chosen) run(() => onReplace(chosen))
              }}
            />
          </>
        )}
        {onDelete && (
          <button type="button" className="danger" disabled={busy} onClick={() => setConfirming(true)}>
            Delete scan
          </button>
        )}
        <span className="viewer-gap" />
        <button type="button" onClick={onClose} aria-label="Close" data-tip="Close (Esc)">
          ✕
        </button>
      </div>
      {note && <p className="viewer-note">{note}</p>}
      {confirming && (
        <div className="confirm" role="alertdialog" aria-modal="true" aria-label="Delete this scan?">
          <p>Delete this scan from the card? The recipe stays.</p>
          <div className="confirm-actions">
            <button type="button" onClick={() => setConfirming(false)}>
              Keep it
            </button>
            <button
              type="button"
              className="danger"
              disabled={busy}
              onClick={() => {
                setConfirming(false)
                run(() => onDelete(), onClose)
              }}
            >
              Delete
            </button>
          </div>
        </div>
      )}
    </div>,
    document.body,
  )
}
