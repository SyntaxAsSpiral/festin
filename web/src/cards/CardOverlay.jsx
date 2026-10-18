import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useAnimate } from 'motion/react'
import { useLocation, useNavigate } from 'react-router'
import { transition } from '../motion.js'
import { useReducedMotion } from '../useReducedMotion.js'
import { KINDS, loadItems, notYet } from './kinds.js'
import { useLookingAt } from './looking.js'
import { forgetOrigin, originRect } from './origin.js'
import { ChatPage, NotePage, RecipePage } from './pages.jsx'

function Confirm({ noun, onYes, onNo }) {
  const yes = useRef(null)
  useEffect(() => yes.current?.focus(), [])
  return (
    <div className="confirm" role="alertdialog" aria-modal="true" aria-label={'Delete this ' + noun + '?'}>
      <p>Delete this {noun}? It can't be brought back.</p>
      <div className="confirm-actions">
        <button type="button" onClick={onNo}>
          Keep it
        </button>
        <button ref={yes} type="button" className="danger" onClick={onYes}>
          Delete
        </button>
      </div>
    </div>
  )
}

// The transform that puts the page over `rect`, turned edge-on.
function fromRect(page, rect) {
  const box = page.getBoundingClientRect()
  return {
    x: rect.left + rect.width / 2 - (box.left + box.width / 2),
    y: rect.top + rect.height / 2 - (box.top + box.height / 2),
    scaleX: rect.width / box.width,
    scaleY: rect.height / box.height,
    rotateY: -90,
    opacity: 0.4,
  }
}

const AT_REST = { x: 0, y: 0, scaleX: 1, scaleY: 1, rotateY: 0, opacity: 1 }

// One card at a time, over its kind's list. Card machine: Opening -> Viewing <-> Editing,
// Delete via Confirm, Closing back into the list (state-machine.md §4).
export function CardOverlay({ kind, id }) {
  const navigate = useNavigate()
  const location = useLocation()
  const reduced = useReducedMotion()
  const [scope, animate] = useAnimate()
  const [item, setItem] = useState(undefined)
  const [phase, setPhase] = useState(id === 'new' ? 'editing' : 'viewing')
  const [draft, setDraft] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [note, setNote] = useState('')
  const closing = useRef(false)
  const spec = KINDS[kind]

  useEffect(() => {
    if (id === 'new') return setItem(null)
    let gone = false
    loadItems(kind).then((items) => !gone && setItem(items.find((it) => it.id === id) || null), () => !gone && setItem(null))
    return () => {
      gone = true
    }
  }, [kind, id])

  // Opening: flip out of the tapped row, or fade in when it isn't on screen.
  useLayoutEffect(() => {
    const page = scope.current
    if (!page || item === undefined) return
    const rect = originRect()
    const motion = transition(reduced, 'flip')
    if (rect) animate(page, { ...fromRect(page, rect) }, { duration: 0 }).then(() => animate(page, AT_REST, motion))
    else animate(page, { opacity: [0, 1] }, motion)
  }, [item === undefined]) // eslint-disable-line react-hooks/exhaustive-deps

  async function close() {
    if (closing.current) return
    closing.current = true
    const page = scope.current
    const rect = originRect()
    const motion = transition(reduced, 'flip')
    if (page) await (rect ? animate(page, fromRect(page, rect), motion) : animate(page, { opacity: 0 }, motion))
    forgetOrigin()
    // Opened from this list: step back. Opened from elsewhere (Meals, a chat link): land on the list.
    if (location.state?.fromList) navigate(-1)
    else navigate('/' + kind, { replace: true })
  }

  function act(promise) {
    setNote('')
    promise.catch((err) => setNote(err.message))
  }

  // Esc closes Confirm first, then leaves editing, then closes the card.
  useEffect(() => {
    function onKey(event) {
      if (event.key !== 'Escape') return
      if (event.target?.closest?.('.surface-panel, #sidebar')) return
      event.preventDefault()
      if (confirming) setConfirming(false)
      else if (phase === 'editing' && id !== 'new') setPhase('viewing')
      else close()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const raw = item?.raw
  const title = id === 'new' ? 'New ' + spec.noun : item?.title || ''
  useLookingAt(title, kind, id === 'new' ? null : item?.id)

  return (
    <div className="card-layer" onClick={(event) => event.target === event.currentTarget && close()}>
      <div ref={scope} className={'card card-' + kind} role="dialog" aria-modal="true" aria-label={title}>
        <div className="card-bar">
          <button type="button" className="card-close" onClick={close}>
            Close
          </button>
        </div>
        <div
          className="card-scroll"
          onClick={(event) => {
            const link = event.target.closest?.('a[data-recipe]')
            if (!link || event.metaKey || event.ctrlKey) return
            event.preventDefault()
            navigate('/recipes/' + link.dataset.recipe)
          }}
        >
          {item === undefined && <p className="lstate">Opening…</p>}
          {item === null && id !== 'new' && <p className="lstate">This {spec.noun} isn't in the box any more.</p>}
          {id === 'new' && (
            <article className="page">
              <p className="quiet">New {spec.noun}s are written here once the new kitchen backend lands. Until then, ask Babette to add one.</p>
            </article>
          )}
          {raw && kind === 'recipes' && <RecipePage recipe={raw} />}
          {raw && kind === 'notes' && (
            <NotePage note={raw} editing={phase === 'editing'} draft={draft} onDraft={setDraft} onColor={() => act(notYet())} />
          )}
          {raw && kind === 'chats' && <ChatPage chat={raw} />}
        </div>
        {raw && (
          <div className="card-foot">
            {kind === 'recipes' && (
              <button type="button" className="card-id" title="Copy the ID" onClick={() => navigator.clipboard?.writeText(raw.id).then(() => setNote('Copied ' + raw.id), () => {})}>
                {raw.id}
              </button>
            )}
            {note && (
              <p className="card-note" role="status">
                {note}
              </p>
            )}
            <div className="card-actions">
              {kind === 'notes' &&
                (phase === 'editing' ? (
                  <button type="button" onClick={() => act(notYet())}>
                    Done
                  </button>
                ) : (
                  <button type="button" onClick={() => (setDraft(raw.text || ''), setPhase('editing'))}>
                    Edit
                  </button>
                ))}
              {kind === 'recipes' && (
                <>
                  <button type="button" onClick={() => act(notYet())}>
                    Edit
                  </button>
                  <button type="button" onClick={() => act(notYet())}>
                    Cooked tonight
                  </button>
                </>
              )}
              {kind === 'chats' && (
                <button type="button" onClick={() => act(notYet())}>
                  Reopen in Babette
                </button>
              )}
              <button type="button" className="danger" onClick={() => setConfirming(true)}>
                Delete
              </button>
            </div>
          </div>
        )}
        {confirming && (
          <Confirm
            noun={spec.noun}
            onNo={() => setConfirming(false)}
            onYes={() => {
              setConfirming(false)
              act(notYet())
            }}
          />
        )}
      </div>
    </div>
  )
}
