import { AnimatePresence, motion } from 'motion/react'
import { transition } from './motion.js'
import { sceneById } from './scenes.js'
import { useReducedMotion } from './useReducedMotion.js'

export function Banner({ sceneId }) {
  const scene = sceneById(sceneId)
  const reduced = useReducedMotion()
  return (
    <div className="banner banner-slide" data-scene={scene.id}>
      <AnimatePresence initial={false}>
        <motion.img
          key={scene.id}
          src={scene.src}
          alt=""
          draggable={false}
          style={{ '--scene-position': scene.position }}
          initial={reduced ? false : { x: '6%', opacity: 0 }}
          animate={{ x: '0%', opacity: 1 }}
          exit={reduced ? { opacity: 1 } : { x: '-6%', opacity: 0 }}
          transition={transition(reduced, 'banner')}
        />
      </AnimatePresence>
      <div className="tint" aria-hidden="true" />
      <div className="dither" aria-hidden="true" />
    </div>
  )
}
