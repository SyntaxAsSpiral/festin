import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate, useSearchParams } from 'react-router'
import { transition } from './motion.js'
import { tabFromPath, TABS } from './tabs.js'
import { Placeholder } from './Placeholder.jsx'
import { CardTab } from './cards/CardTab.jsx'
import { LookingContext } from './cards/looking.js'
import { useReducedMotion } from './useReducedMotion.js'
import Surface, { SurfaceProvider } from './chat/Surface.jsx'
import { ChatPanel, chatHeader, peekLine } from './chat/ChatPanel.jsx'
import { useChat } from './chat/useChat.js'
import { SettingsSidebar, useOpenSettings, useSettingsOpen } from './settings/Sidebar.jsx'
import { Meals } from './meals/Meals.jsx'
import { Frieze } from './meals/Frieze.jsx'
import { fetchPlugins, printerIsOn } from './meals/plan.js'
import './meals/meals.css'

const LOOK = {
  meals: "this week's meals",
  recipes: 'the recipe box',
  notes: 'your notes',
  chats: 'your past chats',
}

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

function Gear() {
  const openSettings = useOpenSettings()
  const settingsOpen = useSettingsOpen()
  const [, setParams] = useSearchParams()
  return (
    <button
      type="button"
      className="ic"
      id="gear"
      aria-label="Settings"
      title="Settings"
      aria-expanded={settingsOpen}
      aria-controls="sidebar"
      onClick={() => {
        if (settingsOpen) {
          const copy = new URLSearchParams(window.location.search)
          copy.delete('settings')
          setParams(copy, { replace: true })
          return
        }
        openSettings('model')
      }}
    >
      ⚙
    </button>
  )
}

function PrintButton({ onMeals }) {
  const [toast, setToast] = useState('')
  useEffect(() => {
    if (!toast) return undefined
    const t = window.setTimeout(() => setToast(''), 3200)
    return () => clearTimeout(t)
  }, [toast])

  async function onPrint() {
    if (!onMeals) {
      setToast('Print the slip from Meals.')
      return
    }
    const plugins = await fetchPlugins()
    if (!printerIsOn(plugins)) {
      setToast('The printer plugin is off.')
      return
    }
    setToast('Sending the slip to the printer…')
  }

  return (
    <>
      <button type="button" className="ic" id="pr" aria-label="Print" title="Print" onClick={onPrint}>
        <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true">
          <path d="M4 6V2h8v4" />
          <rect x="1.5" y="6" width="13" height="6" rx="1" />
          <path d="M4 10h8v4H4z" fill="var(--bb-paper)" />
          <circle cx="12" cy="8" r=".6" fill="currentColor" stroke="none" />
        </svg>
      </button>
      {toast ? (
        <div className="print-toast" role="status">
          {toast}
        </div>
      ) : null}
    </>
  )
}

export function Shell({ boot }) {
  return (
    <SurfaceProvider>
      <ShellFrame boot={boot} />
    </SurfaceProvider>
  )
}

function ShellFrame({ boot }) {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const tab = tabFromPath(pathname)
  const [card, setCard] = useState(null)
  // Each message carries what the cook is looking at: the tab plus a pointer to the open card.
  const chat = useChat({ tab: tab?.id || null, card: card?.id ? { kind: card.kind, id: card.id } : null })
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
    <div className="app" data-app={boot.phase} data-motion={reduced ? 'off' : 'on'} data-frieze={meals ? 'in' : 'out'}>
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
          {meals ? <Frieze /> : <p className="slot-label">Frieze</p>}
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
          <PrintButton onMeals={meals} />
          <FullscreenButton />
          <Gear />
        </header>
        <div className="stage">
          <LookingContext.Provider value={setCard}>
          <Routes>
            <Route index element={<Navigate to="/meals" replace />} />
            <Route path="meals" element={<Meals />} />
            <Route path="recipes/*" element={<CardTab kind="recipes" />} />
            <Route path="notes/*" element={<CardTab kind="notes" />} />
            <Route path="chats/*" element={<CardTab kind="chats" />} />
            <Route path="*" element={<Placeholder id="missing" />} />
          </Routes>
          </LookingContext.Provider>
        </div>
      </div>
      <Surface peekLine={peekLine(chat)} lookingAt={card?.title || LOOK[tab?.id] || 'the kitchen'} header={chatHeader(chat)}>
        <ChatPanel chat={chat} />
      </Surface>
      <SettingsSidebar />
    </div>
  )
}
