import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useAnimate } from 'motion/react'
import { useLocation, useNavigate } from 'react-router'
import { transition } from '../motion.js'
import { useReducedMotion } from '../useReducedMotion.js'
import { useSurface } from '../chat/Surface.jsx'
import {
  ConflictError,
  KINDS,
  cookTonight,
  loadItem,
  pointSessionAt,
  removeItem,
  saveNote,
  saveRecipe,
  toItem,
} from './kinds.js'
import { useLookingAt } from './looking.js'
import { forgetOrigin, originRect } from './origin.js'
import { ChatPage, NotePage, RecipeEditor, RecipePage } from './pages.jsx'

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

function blankRecipe() {
  return { title: '', category: '', ingredients: '', method: '', notes: '' }
}

function draftFrom(recipe) {
  return {
    title: recipe.title || '',
    category: recipe.category || '',
    ingredients: (recipe.ingredients || []).join('\n'),
    method: recipe.method || '',
    notes: recipe.notes || '',
  }
}

// One card at a time, over its kind's list. Card machine: Opening -> Viewing <-> Editing,
// Delete via Confirm, Closing back into the list (state-machine.md §4).
export function CardOverlay({ kind, id, onChanged }) {
  const navigate = useNavigate()
  const location = useLocation()
  const reduced = useReducedMotion()
  const { open } = useSurface()
  const [scope, animate] = useAnimate()
  const [item, setItem] = useState(() => (id === 'new' ? null : undefined))
  const [phase, setPhase] = useState(id === 'new' ? 'editing' : 'viewing')
  const [draft, setDraft] = useState('')
  const [noteColor, setNoteColor] = useState('none')
  const [recipeDraft, setRecipeDraft] = useState(blankRecipe)
  const [confirming, setConfirming] = useState(false)
  const [note, setNote] = useState('')
  const closing = useRef(false)
  const spec = KINDS[kind]

  useEffect(() => {
    if (id === 'new') return setItem(null)
    let gone = false
    loadItem(kind, id).then((next) => !gone && setItem(next), () => !gone && setItem(null))
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

  function act(work) {
    setNote('')
    return Promise.resolve()
      .then(work)
      .catch(async (err) => {
        setNote(err.message || 'The kitchen did not save that.')
        if (err instanceof ConflictError && id !== 'new') {
          const next = await loadItem(kind, id).catch(() => null)
          setItem(next)
          setPhase('viewing')
          onChanged?.()
        }
      })
  }

  function applySaved(record, stay) {
    setItem(toItem(kind, record))
    if (!stay) setPhase('viewing')
    onChanged?.()
  }

  function openSaved(record) {
    onChanged?.()
    navigate('/' + kind + '/' + encodeURIComponent(record.id), { replace: true, state: location.state })
  }

  // Esc closes Confirm first, then leaves editing, then closes the card.
  useEffect(() => {
    function onKey(event) {
      if (event.key !== 'Escape') return
      if (event.target?.closest?.('.surface-panel')) return
      event.preventDefault()
      if (confirming) setConfirming(false)
      else if (phase === 'editing' && id !== 'new') setPhase('viewing')
      else close()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const raw = item?.raw
  const creating = id === 'new'
  const editingRecipe = kind === 'recipes' && (creating || phase === 'editing')
  const editingNote = kind === 'notes' && (creating || phase === 'editing')
  const title = creating ? 'New ' + spec.noun : item?.title || ''
  useLookingAt(title, kind, creating ? null : item?.id)

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
          {item === null && !creating && <p className="lstate">This {spec.noun} isn't in the box any more.</p>}
          {editingRecipe && <RecipeEditor draft={recipeDraft} onDraft={setRecipeDraft} />}
          {raw && kind === 'recipes' && phase !== 'editing' && <RecipePage recipe={raw} />}
          {(raw || creating) && kind === 'notes' && (
            <NotePage
              note={creating ? { type: 'note', text: draft, color: noteColor, date: '' } : raw}
              editing={editingNote}
              draft={draft}
              onDraft={setDraft}
              onColor={(color) => {
                if (creating) setNoteColor(color)
                else act(() => saveNote(raw, { color }).then((saved) => applySaved(saved, phase === 'editing')))
              }}
            />
          )}
          {raw && kind === 'chats' && <ChatPage chat={raw} />}
        </div>
        {(raw || creating) && (
          <div className="card-foot">
            {kind === 'recipes' && raw && !editingRecipe && (
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
              {editingRecipe && (
                <>
                  <button type="button" onClick={() => (creating ? close() : setPhase('viewing'))}>
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      act(() =>
                        saveRecipe(creating ? null : raw, recipeDraft).then((saved) => (creating ? openSaved(saved) : applySaved(saved))),
                      )
                    }
                  >
                    Save
                  </button>
                </>
              )}
              {kind === 'notes' &&
                (editingNote ? (
                  <button
                    type="button"
                    onClick={() =>
                      act(() =>
                        saveNote(creating ? null : raw, { text: draft, color: creating ? noteColor : undefined }).then((saved) =>
                          creating ? openSaved(saved) : applySaved(saved),
                        ),
                      )
                    }
                  >
                    Done
                  </button>
                ) : (
                  <button type="button" onClick={() => (setDraft(raw.text || ''), setPhase('editing'))}>
                    Edit
                  </button>
                ))}
              {kind === 'recipes' && raw && !editingRecipe && (
                <>
                  <button type="button" onClick={() => (setRecipeDraft(draftFrom(raw)), setPhase('editing'))}>
                    Edit
                  </button>
                  <button type="button" onClick={() => act(() => cookTonight(raw).then(() => setNote('Cooked tonight.')))}>
                    Cooked tonight
                  </button>
                </>
              )}
              {kind === 'chats' && raw && (
                <button type="button" onClick={() => act(() => pointSessionAt(raw.id).then(() => open()))}>
                  Reopen in Babette
                </button>
              )}
              {raw && !editingRecipe && (
                <button type="button" className="danger" onClick={() => setConfirming(true)}>
                  Delete
                </button>
              )}
            </div>
          </div>
        )}
        {confirming && (
          <Confirm
            noun={spec.noun}
            onNo={() => setConfirming(false)}
            onYes={() => {
              setConfirming(false)
              act(() => removeItem(kind, raw).then(() => (onChanged?.(), close())))
            }}
          />
        )}
      </div>
    </div>
  )
}
