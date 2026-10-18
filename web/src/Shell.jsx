import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router'
import { transition } from './motion.js'
import { tabFromPath, TABS } from './tabs.js'
import { Placeholder } from './Placeholder.jsx'
import { useReducedMotion } from './useReducedMotion.js'

function typingTarget(el) {
  if (!el || typeof el.closest !== 'function') return false
  return Boolean(el.closest('input, textarea, select, [contenteditable="true"]'))
}

function FullscreenButton() {
  const [on, setOn] = useState(false)
  useEffect(() => {
    const sync = () => setOn(Boolean(document.fullscreenElement))
    document.addEventListener('fullscreenchange', sync)
    return () => document.removeEventListener('fullscreenchange', sync)
  }, [])
  async function toggle() {
    try {
      if (document.fullscreenElement) await document.exitFullscreen()
      else await document.documentElement.requestFullscreen()
    } catch {
      /* the browser refused; leave the button as it is */
    }
  }
  const label = on ? 'Exit full screen' : 'Full screen'
  return (
    <button type="button" className="ic" id="fs" aria-label={label} title={label} onClick={toggle}>
      {on ? '🗗' : '⛶'}
    </button>
  )
}

export function Shell({ boot }) {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const tab = tabFromPath(pathname)
  const trouble = boot.phase === 'trouble'
  const meals = tab?.id === 'meals'
  const reduced = useReducedMotion()

  useEffect(() => {
    function onKey(event) {
      if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return
      if (typingTarget(event.target)) return
      const next = TABS.find((item) => item.key.toLowerCase() === event.key.toLowerCase())
      if (!next) return
      if (pathname === next.path || pathname.startsWith(next.path + '/')) return
      event.preventDefault()
      navigate(next.path)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navigate, pathname])

  return (
    <div className={trouble ? 'app trouble' : 'app'} data-app={boot.phase} data-motion={reduced ? 'off' : 'on'} data-frieze={meals ? 'in' : 'out'}>
      {trouble && (
        <div className="trouble" role="status">
          <p>The kitchen is quiet just now. This is the last copy, and it is read only.</p>
          <button type="button" onClick={boot.retry}>Try again</button>
        </div>
      )}
      <div className="frieze-slot">
        <motion.aside
          className="frieze frieze-scroll"
          aria-label="Frieze"
          aria-hidden={meals ? undefined : true}
          initial={false}
          animate={{ x: meals ? '0%' : '-100%', opacity: meals ? 1 : 0.6 }}
          transition={transition(reduced, 'drawer')}
        >
          <p className="slot-label">Frieze</p>
        </motion.aside>
      </div>
      <div className="main">
        <header className="bar">
          <nav className="views" aria-label="Sections">
            {TABS.map((item) => (
              <NavLink key={item.id} to={item.path} className={({ isActive }) => (isActive ? 'on' : undefined)}>
                {item.label} <kbd>{item.key}</kbd>
              </NavLink>
            ))}
          </nav>
          <span className="bar-gap" />
          <button type="button" className="ic" id="pr" aria-label="Print" title="Print">
            <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true">
              <path d="M4 6V2h8v4" />
              <rect x="1.5" y="6" width="13" height="6" rx="1" />
              <path d="M4 10h8v4H4z" fill="var(--bb-paper)" />
              <circle cx="12" cy="8" r=".6" fill="currentColor" stroke="none" />
            </svg>
          </button>
          <FullscreenButton />
          <button type="button" className="ic" id="gear" aria-label="Settings" title="Settings">⚙</button>
        </header>
        <div className="stage">
          <Routes>
            <Route index element={<Navigate to="/meals" replace />} />
            <Route path="meals" element={<Placeholder id="meals" />} />
            <Route path="recipes" element={<Placeholder id="recipes" />} />
            <Route path="recipes/*" element={<Placeholder id="recipes" />} />
            <Route path="notes" element={<Placeholder id="notes" />} />
            <Route path="notes/*" element={<Placeholder id="notes" />} />
            <Route path="chats" element={<Placeholder id="chats" />} />
            <Route path="chats/*" element={<Placeholder id="chats" />} />
            <Route path="*" element={<Placeholder id="missing" />} />
          </Routes>
        </div>
      </div>
      <aside className="chatslot" aria-label="Chat">
        <p>Babette</p>
      </aside>
    </div>
  )
}
