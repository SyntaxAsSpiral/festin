import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { transition } from '../motion.js'
import { SCENES } from '../scenes.js'
import { useReducedMotion } from '../useReducedMotion.js'

function rnd(lo, hi) {
  return lo + Math.random() * (hi - lo)
}

// Top slip vignette: original art, turns every 45–50 s with the banner slide.
export function SlipBanner() {
  const reduced = useReducedMotion()
  const [index, setIndex] = useState(() => Math.floor(Math.random() * SCENES.length))
  const scene = SCENES[index]

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
    <div className="vig banner-slide" data-art="top" aria-hidden="true">
      <AnimatePresence initial={false}>
        <motion.img
          key={scene.id}
          src={scene.src}
          alt=""
          draggable={false}
          style={{ '--scene-position': scene.position }}
          initial={reduced ? false : { x: '100%' }}
          animate={{ x: '0%' }}
          exit={reduced ? { opacity: 1 } : { x: '-100%' }}
          transition={transition(reduced, 'banner')}
        />
      </AnimatePresence>
    </div>
  )
}
