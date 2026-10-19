import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { transition } from '../motion.js'
import { SCENES, cropFor } from '../scenes.js'
import { useReducedMotion } from '../useReducedMotion.js'

function rnd(lo, hi) {
  return lo + Math.random() * (hi - lo)
}

// Top slip vignette: original art, turns every 45–50 s with the banner slide.
export function SlipBanner() {
  const reduced = useReducedMotion()
  const [index, setIndex] = useState(() => Math.floor(Math.random() * SCENES.length))
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
    schedule(true)
    const onVis = () => {
      clearTimeout(timer)
      if (!document.hidden) schedule(true)
    }
    document.addEventListener('visibilitychange', onVis)
    return () => {
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [])

  return (
    <div className="vig banner-slide" data-art="top" aria-hidden="true" ref={vigRef}>
      <AnimatePresence initial={false}>
        <motion.img
          key={scene.id}
          src={scene.src}
          alt=""
          draggable={false}
          className={crop ? 'zoned' : undefined}
          style={
            crop
              ? { width: crop.width, height: crop.height, left: crop.left, top: crop.top }
              : { '--scene-position': scene.position }
          }
          initial={reduced ? false : { x: '100%' }}
          animate={{ x: '0%' }}
          exit={reduced ? { opacity: 1 } : { x: '-100%' }}
          transition={transition(reduced, 'banner')}
        />
      </AnimatePresence>
    </div>
  )
}
