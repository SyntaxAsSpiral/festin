import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useAnimate } from 'motion/react'
import { useLocation, useNavigate } from 'react-router'
import { transition } from '../motion.js'
import { useReducedMotion } from '../useReducedMotion.js'
import { useSurface } from '../chat/Surface.jsx'
import {
  ConflictError,
  KINDS,
  clearRecipeCooks,
  cookedNote,
  loadItem,
  markRecipeCooked,
  pointSessionAt,
  removeItem,
  removeRecipePhoto,
  removeRecipeScan,
  replaceRecipeScan,
  saveNote,
  saveRecipe,
  toggleNote,
  setRecipeFavourite,
  setRecipeQueued,
  toItem,
  updateRecipePhotos,
  cookedMeta,
} from './kinds.js'
import { copyText } from '../secure.js'
import { useLookingAt } from './looking.js'
import { forgetOrigin, originRect } from './origin.js'
import { ArtIcon } from './ArtIcon.jsx'
import { ChatPage, NotePage, RecipeEditor, RecipePage } from './pages.jsx'

const MAX_PHOTO_BYTES = 10 * 1024 * 1024
const MAX_PHOTOS_AT_ONCE = 4

function readAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = () => reject(new Error('Could not read ' + file.name))
    reader.readAsDataURL(file)
  })
}

function Confirm({ label, message, keepLabel = 'Keep it', yesLabel = 'Delete', onYes, onNo }) {
  const yes = useRef(null)
  useEffect(() => yes.current?.focus(), [])
  return (
    <div className="confirm" role="alertdialog" aria-modal="true" aria-label={label}>
      <p>{message}</p>
      <div className="confirm-actions">
        <button type="button" onClick={onNo}>
          {keepLabel}
        </button>
        <button ref={yes} type="button" className="danger" onClick={onYes}>
          {yesLabel}
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
  return { title: '', kind: 'formule', category: '', ingredients: '', appliesTo: '', method: '', notes: '', context: '' }
}

function draftFrom(recipe) {
  return {
    title: recipe.title || '',
    kind: recipe.kind === 'praxis' ? 'praxis' : 'formule',
    category: recipe.category || '',
    ingredients: (recipe.ingredients || []).join('\n'),
    appliesTo: (recipe.appliesTo || []).join('\n'),
    method: recipe.method || '',
    notes: recipe.notes || '',
    context: recipe.context || '',
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
  const [confirming, setConfirming] = useState(null)
  const [note, setNote] = useState('')
  const [photoBusy, setPhotoBusy] = useState(false)
  const closing = useRef(false)
  const photoPicker = useRef(null)
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

  // Scan changes come from the viewer, which shows its own errors; a conflict reloads the card.
  function scanWork(work) {
    return Promise.resolve()
      .then(work)
      .then((saved) => {
        applySaved(saved, true)
        return saved
      })
      .catch(async (err) => {
        if (err instanceof ConflictError) {
          const next = await loadItem(kind, id).catch(() => null)
          if (next) setItem(next)
          onChanged?.()
        }
        throw err
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
      if (event.target?.closest?.('.surface-panel, #sidebar')) return
      event.preventDefault()
      if (confirming) setConfirming(null)
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

  async function addPhotos(files) {
    if (!raw || photoBusy) return
    const list = [...files]
    if (!list.length) return
    if (list.length > MAX_PHOTOS_AT_ONCE) {
      setNote('Choose up to four photos at a time.')
      return
    }
    for (const file of list) {
      if (file.size > MAX_PHOTO_BYTES) {
        setNote('Each photo must be under 10 MB.')
        return
      }
    }
    setPhotoBusy(true)
    setNote('')
    try {
      const photos = []
      for (const file of list) photos.push(await readAsDataUrl(file))
      await act(() =>
        updateRecipePhotos(raw, photos).then((saved) => {
          applySaved(saved)
          setNote(photos.length === 1 ? 'Photo added.' : photos.length + ' photos added.')
        }),
      )
    } finally {
      setPhotoBusy(false)
    }
  }

  return (
    <div className="card-layer" onClick={(event) => event.target === event.currentTarget && close()}>
      <div
        ref={scope}
        className={
          'card card-' + kind +
          (kind === 'recipes' && raw?.favourite ? ' card-is-fav' : '') +
          (kind === 'recipes' && raw?.queuedAt ? ' card-is-queued' : '') +
          (kind === 'recipes' && raw?.kind === 'praxis' ? ' card-is-praxis' : '')
        }
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="card-bar">
          {raw && (kind === 'recipes' ? !editingRecipe : kind === 'notes' ? !editingNote : false) && (
            <button
              type="button"
              className="card-icon"
              aria-label="Edit"
              data-tip="Edit"
              onClick={() =>
                kind === 'recipes' ? (setRecipeDraft(draftFrom(raw)), setPhase('editing')) : (setDraft(raw.text || ''), setPhase('editing'))
              }
            >
              <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M10.5 2.5l3 3L6 13l-3.5.5L3 10z" />
                <path d="M9 4l3 3" />
              </svg>
            </button>
          )}
          {raw && !editingRecipe && (
            <button type="button" className="card-icon danger" aria-label="Delete" data-tip="Delete" onClick={() => setConfirming({ type: 'delete' })}>
              <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M2.5 4.5h11M6 4.5V3h4v1.5M4 4.5l.7 9h6.6l.7-9M6.6 7v4.5M9.4 7v4.5" />
              </svg>
            </button>
          )}
          <button type="button" className="card-icon card-close" onClick={close} aria-label="Close" data-tip="Close (Esc)">
            <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" aria-hidden="true">
              <path d="M4 4l8 8M12 4l-8 8" />
            </svg>
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
          {raw && kind === 'recipes' && phase !== 'editing' && (
            <RecipePage
              recipe={raw}
              onRemovePhoto={(path) => setConfirming({ type: 'photo', path })}
              onReplaceScan={(path, file) =>
                scanWork(async () => {
                  if (file.size > MAX_PHOTO_BYTES) throw new Error('Each photo must be under 10 MB.')
                  return replaceRecipeScan(raw, path, await readAsDataUrl(file))
                })
              }
              onRemoveScan={(path) => scanWork(() => removeRecipeScan(raw, path))}
            />
          )}
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
              <>
                <button type="button" className="card-id" title="Copy the ID" onClick={() => copyText(raw.id).then(() => setNote('Copied ' + raw.id), () => setNote('Select the ID to copy it: ' + raw.id))}>
                  {raw.id}
                </button>
                {/* The count rides on the button, so a press shows it landed. */}
                <button
                  type="button"
                  className="card-cooked"
                  title={(cookedMeta(raw) || 'Not cooked yet') + (raw.cookCount ? ' · right-click or hold to clear' : '')}
                  onContextMenu={(event) => {
                    event.preventDefault()
                    if (raw.cookCount) setConfirming({ type: 'cooks' })
                  }}
                  onClick={() =>
                    act(() =>
                      markRecipeCooked(raw).then((saved) => {
                        setNote(cookedNote(raw, saved))
                        applySaved(saved)
                      }),
                    )
                  }
                >
                  <span className="card-cooked-mark" aria-hidden="true" />
                  Cooked{raw.cookCount ? <span className="card-cooked-n"> · {raw.cookCount}</span> : null}
                </button>
              </>
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
                    className="card-save"
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
                    className="card-save"
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
                  <>
                    {raw && (
                      <button
                        type="button"
                        className="card-pin"
                        onClick={() => act(() => toggleNote(raw).then((saved) => applySaved(saved)))}
                      >
                        {raw.open ? 'Archive' : 'Pin'}
                      </button>
                    )}
                  </>
                ))}
              {kind === 'recipes' && raw && !editingRecipe && (
                <>
                  <button
                    type="button"
                    className={'card-fav' + (raw.favourite ? ' on' : '')}
                    aria-pressed={Boolean(raw.favourite)}
                    title={raw.favourite ? 'Favourited' : 'Favourite'}
                    aria-label={raw.favourite ? 'Favourited' : 'Favourite'}
                    onClick={() =>
                      act(() =>
                        setRecipeFavourite(raw, !raw.favourite).then((saved) => {
                          applySaved(saved)
                          setNote(saved.favourite ? 'Favourited.' : 'Favourite cleared.')
                        }),
                      )
                    }
                  >
                    <ArtIcon name={raw.favourite ? 'heart-on' : 'heart-off'} /> <span className="lbl">Favourite</span>
                  </button>
                  <button
                    type="button"
                    className={'card-queue' + (raw.queuedAt ? ' on' : '')}
                    aria-pressed={Boolean(raw.queuedAt)}
                    title={raw.queuedAt ? 'On the to-cook queue' : 'To cook'}
                    aria-label={raw.queuedAt ? 'On the to-cook queue' : 'To cook'}
                    onClick={() =>
                      act(() =>
                        setRecipeQueued(raw, !raw.queuedAt).then((saved) => {
                          applySaved(saved)
                          setNote(saved.queuedAt ? 'On the to-cook queue.' : 'Off the to-cook queue.')
                        }),
                      )
                    }
                  >
                    <ArtIcon name={raw.queuedAt ? 'bookmark-on' : 'bookmark-off'} /> <span className="lbl">To cook</span>
                  </button>
                  <button type="button" className="card-photo" disabled={photoBusy} onClick={() => photoPicker.current?.click()}>
                    + Photo
                  </button>
                  <input
                    ref={photoPicker}
                    type="file"
                    accept="image/jpeg,image/png,image/webp"
                    multiple
                    hidden
                    onChange={(event) => {
                      addPhotos(event.target.files || []).catch((err) => setNote(err.message || 'Could not read that photo.'))
                      event.target.value = ''
                    }}
                  />
                </>
              )}
              {kind === 'chats' && raw && (
                <button type="button" className="card-reopen" onClick={() => act(() => pointSessionAt(raw.id).then(() => open()))}>
                  Reopen in Babette
                </button>
              )}
            </div>
          </div>
        )}
        {confirming?.type === 'delete' && (
          <Confirm
            label={'Delete this ' + spec.noun + '?'}
            message={'Delete this ' + spec.noun + "? It can't be brought back."}
            onNo={() => setConfirming(null)}
            onYes={() => {
              setConfirming(null)
              act(() => removeItem(kind, raw).then(() => (onChanged?.(), close())))
            }}
          />
        )}
        {confirming?.type === 'cooks' && (
          <Confirm
            label="Clear the cooks?"
            message="Clear this recipe's recorded cooks and their Kitchen Log entries? Dinners on past weeks' slips still count. It can't be brought back."
            keepLabel="Keep them"
            yesLabel="Clear"
            onNo={() => setConfirming(null)}
            onYes={() => {
              setConfirming(null)
              act(() =>
                clearRecipeCooks(raw).then((saved) => {
                  applySaved(saved)
                  setNote(saved.cookCount ? 'Cooks cleared; ' + saved.cookCount + ' from past slips remain.' : 'Cooks cleared.')
                }),
              )
            }}
          />
        )}
        {confirming?.type === 'photo' && (
          <Confirm
            label="Remove this photo?"
            message="Remove this cooked photo from the card?"
            keepLabel="Keep it"
            yesLabel="Remove"
            onNo={() => setConfirming(null)}
            onYes={() => {
              const path = confirming.path
              setConfirming(null)
              act(() =>
                removeRecipePhoto(raw, path).then((saved) => {
                  applySaved(saved)
                  setNote('Photo removed.')
                }),
              )
            }}
          />
        )}
      </div>
    </div>
  )
}
