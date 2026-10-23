import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { transition } from '../motion.js'
import { SCENES, cropFor } from '../scenes.js'
import { useReducedMotion } from '../useReducedMotion.js'

function rnd(lo, hi) {
  return lo + Math.random() * (hi - lo)
}

const SWIPE = { duration: 0.45, ease: [0.22, 1, 0.36, 1] }

// A scene comes in from the side it is swiped from and leaves by the other.
const slide = {
  enter: ({ dir, w }) => ({ x: w ? dir * w : dir > 0 ? '100%' : '-100%' }),
  center: { x: 0 },
  exit: ({ dir, w, swipe, reduced }) =>
    reduced
      ? { opacity: 1, transition: { duration: 0 } }
      : { x: w ? -dir * w : dir > 0 ? '-100%' : '100%', ...(swipe ? { transition: SWIPE } : {}) },
}

// Top slip vignette: original art, turns every 45–50 s with the banner slide.
// Swipe it (or drag it) for the next scene, or back for the one before.
export function SlipBanner() {
  const reduced = useReducedMotion()
  const [index, setIndex] = useState(() => Math.floor(Math.random() * SCENES.length))
  const [turn, setTurn] = useState({ dir: 1, swipe: 0 })
  const scene = SCENES[index]
  // The banner's size, so a zoned scene can be cropped to it.
  const vigRef = useRef(null)
  const [box, setBox] = useState(null)
  useLayoutEffect(() => {
    const el = vigRef.current
    if (!el) return undefined
    const measure = () => setBox({ w: el.clientWidth, h: el.clientHeight })
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const crop = scene.zone && box?.w && box?.h ? cropFor(box.w, box.h, scene.zone) : null

  useEffect(() => {
    if (document.hidden) return undefined
    let timer = 0
    const schedule = (lead) => {
      clearTimeout(timer)
      const ms = lead ? rnd(7000, 10000) : rnd(45000, 50000)
      timer = window.setTimeout(() => {
        if (document.hidden) return
        setTurn((t) => ({ ...t, dir: 1, swiping: false }))
        setIndex((cur) => {
          let next = Math.floor(Math.random() * SCENES.length)
          if (SCENES.length > 1) {
            while (next === cur) next = Math.floor(Math.random() * SCENES.length)
          }
          return next
        })
        schedule(false)
      }, ms)
    }
    // A swipe restarts the clock, so the scene chosen stays its full while.
    schedule(turn.swipe === 0)
    const onVis = () => {
      clearTimeout(timer)
      if (!document.hidden) schedule(true)
    }
    document.addEventListener('visibilitychange', onVis)
    return () => {
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [turn.swipe])

  function go(dir) {
    setTurn((t) => ({ dir, swipe: t.swipe + 1, swiping: true }))
    setIndex((cur) => (cur + dir + SCENES.length) % SCENES.length)
  }

  const w = box?.w || 0
  const custom = { dir: turn.dir, w, swipe: turn.swiping, reduced }

  return (
    <div className="vig banner-slide" data-art="top" aria-hidden="true" ref={vigRef}>
      <AnimatePresence initial={false} custom={custom}>
        <motion.img
          key={scene.id}
          src={scene.src}
          alt=""
          draggable={false}
          className={crop ? 'zoned' : undefined}
          style={{
            touchAction: 'pan-y',
            ...(crop
              ? { width: crop.width, height: crop.height, left: crop.left, top: crop.top }
              : { '--scene-position': scene.position }),
          }}
          custom={custom}
          variants={slide}
          initial={reduced ? false : 'enter'}
          animate="center"
          exit="exit"
          transition={turn.swiping && !reduced ? SWIPE : transition(reduced, 'banner')}
          drag="x"
          dragConstraints={{ left: 0, right: 0 }}
          dragElastic={0.7}
          dragMomentum={false}
          onDragEnd={(e, info) => {
            // Far enough, or flung: a fifth of the banner, counting the fling.
            const reach = info.offset.x + info.velocity.x * 0.2
            const need = (w || 300) / 5
            if (reach < -need) go(1)
            else if (reach > need) go(-1)
          }}
        />
      </AnimatePresence>
    </div>
  )
}
