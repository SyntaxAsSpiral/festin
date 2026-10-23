import { useState } from 'react'
import { Message } from '../chat/Transcript.jsx'
import { CATEGORY_LABELS, chatDate, dayOf, plateFor, provenance, sourceOf } from './kinds.js'
import { ScanViewer } from './ScanViewer.jsx'

// Live stores file paths under data/; the kitchen serves them at these URLs.
function served(path) {
  const p = String(path || '')
  if (p.startsWith('data/cards/')) return '/cards/' + p.slice('data/cards/'.length)
  if (p.startsWith('data/cooking-photos/')) return '/photos/' + p.slice('data/cooking-photos/'.length)
  return p
}

function Paragraphs({ text, className }) {
  const paras = String(text || '')
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean)
  if (!paras.length) return null
  return (
    <div className={className}>
      {paras.map((p, i) => (
        <p key={i}>{p}</p>
      ))}
    </div>
  )
}

function CookedPhoto({ path, src, title, onOpen, onRemove }) {
  return (
    <figure className="cooked-photo">
      <button type="button" className="cooked-photo-open" onClick={() => onOpen(src)} aria-label="Open the photo">
        <img src={src} alt={'Cooked: ' + title} loading="lazy" />
      </button>
      {onRemove && (
        <button type="button" className="photo-remove" onClick={() => onRemove(path)}>
          Remove
        </button>
      )}
    </figure>
  )
}

export function RecipePage({ recipe, onRemovePhoto, onReplaceScan, onRemoveScan }) {
  // { src } for a cooked photo, { src, scan } for a box scan (scan: its stored path).
  const [openImage, setOpenImage] = useState(null)
  const scans = (recipe.ocrPhotos || []).map((path) => ({ path, src: served(path) }))
  const photos = (recipe.photos || []).map((path) => ({ path, src: served(path) }))
  const ingredients = Array.isArray(recipe.ingredients) ? recipe.ingredients : []
  const appliesTo = Array.isArray(recipe.appliesTo) ? recipe.appliesTo : []
  const praxis = recipe.kind === 'praxis'
  const seeAlso = praxis || !Array.isArray(recipe.seeAlso) ? [] : recipe.seeAlso.filter((item) => item && item.id && item.title)
  const empty = praxis ? !recipe.method && !appliesTo.length : !ingredients.length && !recipe.method
  return (
    <article className={'page page-recipe' + (praxis ? ' page-praxis' : '')}>
      <img className="frontis" src={plateFor(recipe.category)} alt="" />
      <header className="page-head">
        <h1>{recipe.title}</h1>
        <p className="prov">
          {praxis && <span className="form-mark">Praxis</span>}
          {provenance(recipe)}
        </p>
        {sourceOf(recipe) && <p className="prov prov-source">Source: {sourceOf(recipe)}</p>}
      </header>
      {recipe.searchDescription && <p className="standfirst">{recipe.searchDescription}</p>}
      <div className="recipe-body">
        {/* Cooked photos are the recipe's pictures; the box scan is a reference, kept below. */}
        {photos[0] && (
          <figure className="from-box">
            <button type="button" className="cooked-photo-open" onClick={() => setOpenImage({ src: photos[0].src })} aria-label="Open the photo">
              <img src={photos[0].src} alt={'Cooked: ' + recipe.title} loading="lazy" />
            </button>
            <figcaption>From our kitchen</figcaption>
            {onRemovePhoto && (
              <button type="button" className="photo-remove" onClick={() => onRemovePhoto(photos[0].path)}>
                Remove
              </button>
            )}
          </figure>
        )}
        {praxis ? (
          <>
            {recipe.method && (
              <section className="method">
                <h2>Method</h2>
                <Paragraphs text={recipe.method} />
              </section>
            )}
            {appliesTo.length > 0 && (
              <section className="applies-to">
                <h2>Applies to</h2>
                <ul>
                  {appliesTo.map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ul>
              </section>
            )}
            {ingredients.length > 0 && (
              <section className="ingredients">
                <h2>Ingredients</h2>
                <ul>
                  {ingredients.map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ul>
              </section>
            )}
          </>
        ) : (
          <>
            {ingredients.length > 0 && (
              <section className="ingredients">
                <h2>Ingredients</h2>
                <ul>
                  {ingredients.map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ul>
              </section>
            )}
            {recipe.method && (
              <section className="method">
                <h2>Method</h2>
                <Paragraphs text={recipe.method} />
              </section>
            )}
            {seeAlso.length > 0 && (
              <p className="see-also">
                See also:{' '}
                {seeAlso.map((item, i) => (
                  <span key={item.id}>
                    {i > 0 ? ', ' : null}
                    <a className="cbk cbk-title" href={'/recipes/' + encodeURIComponent(item.id)} data-recipe={item.id}>
                      {item.title}
                    </a>
                  </span>
                ))}
              </p>
            )}
          </>
        )}
        {empty && <p className="quiet">{praxis ? 'This praxis has no method yet.' : 'This card has no ingredients or method yet.'}</p>}
      </div>
      {photos.length > 1 && (
        <div className="cooked-photos">
          {photos.slice(1).map((photo) => (
            <CookedPhoto
              key={photo.path}
              path={photo.path}
              src={photo.src}
              title={recipe.title}
              onOpen={(src) => setOpenImage({ src })}
              onRemove={onRemovePhoto}
            />
          ))}
        </div>
      )}
      {String(recipe.notes || '').trim() && (
        <section className="kitchen">
          <p className="fleuron" aria-hidden="true">
            ❦
          </p>
          <h2>In the kitchen</h2>
          <Paragraphs text={recipe.notes} />
        </section>
      )}
      {String(recipe.context || '').trim() && (
        <section className="kitchen babble">
          <h2>
            Babette's babble <small>not printed</small>
          </h2>
          <Paragraphs text={recipe.context} />
        </section>
      )}
      {scans.length > 0 && (
        <section className="kitchen babble scans">
          <h2>
            From the box <small>original {scans.length > 1 ? 'cards' : 'card'}</small>
          </h2>
          <div className="scan-strip">
            {scans.map((scan) => (
              <button key={scan.path} type="button" onClick={() => setOpenImage({ src: scan.src, scan: scan.path })} aria-label="Open the original card">
                <img src={scan.src} alt={'The original card for ' + recipe.title} loading="lazy" />
              </button>
            ))}
          </div>
        </section>
      )}
      {openImage && (
        <ScanViewer
          src={openImage.src}
          alt={openImage.scan ? 'The original card for ' + recipe.title : recipe.title}
          onClose={() => setOpenImage(null)}
          onReplace={
            openImage.scan && onReplaceScan
              ? (file) =>
                  onReplaceScan(openImage.scan, file).then((saved) => {
                    // The new scan takes the old one's place in the list.
                    const at = scans.findIndex((x) => x.path === openImage.scan)
                    const path = (saved?.ocrPhotos || [])[at]
                    if (path) setOpenImage({ src: served(path), scan: path })
                  })
              : null
          }
          onDelete={openImage.scan && onRemoveScan ? () => onRemoveScan(openImage.scan) : null}
        />
      )}
    </article>
  )
}

export function RecipeEditor({ draft, onDraft }) {
  function set(key, value) {
    onDraft({ ...draft, [key]: value })
  }
  const known = Object.prototype.hasOwnProperty.call(CATEGORY_LABELS, draft.category)
  const praxis = draft.kind === 'praxis'
  return (
    <article className={'page page-recipe' + (praxis ? ' page-praxis' : '')}>
      <img className="frontis" src={plateFor(draft.category)} alt="" />
      <header className="page-head">
        <input className="page-title" aria-label="Title" value={draft.title} placeholder="Title" onChange={(e) => set('title', e.target.value)} autoFocus />
        <div className="page-form-row">
          <select className="page-form" aria-label="Form" value={praxis ? 'praxis' : 'formule'} onChange={(e) => set('kind', e.target.value)}>
            <option value="formule">Formule</option>
            <option value="praxis">Praxis</option>
          </select>
          <select className="page-cat" aria-label="Category" value={draft.category || ''} onChange={(e) => set('category', e.target.value)}>
            <option value="">Uncategorized</option>
            {!known && draft.category ? <option value={draft.category}>{draft.category}</option> : null}
            {Object.entries(CATEGORY_LABELS).map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </div>
      </header>
      <div className="recipe-body">
        {praxis ? (
          <>
            <section className="method">
              <h2>Method</h2>
              <textarea className="page-area" aria-label="Method" value={draft.method} onChange={(e) => set('method', e.target.value)} />
            </section>
            <section className="applies-to">
              <h2>Applies to</h2>
              <textarea
                className="page-area"
                aria-label="Applies to"
                value={draft.appliesTo}
                placeholder="Bare nouns, one on each line"
                onChange={(e) => set('appliesTo', e.target.value)}
              />
            </section>
          </>
        ) : (
          <>
            <section className="ingredients">
              <h2>Ingredients</h2>
              <textarea className="page-area" aria-label="Ingredients" value={draft.ingredients} placeholder="One ingredient on each line" onChange={(e) => set('ingredients', e.target.value)} />
            </section>
            <section className="method">
              <h2>Method</h2>
              <textarea className="page-area" aria-label="Method" value={draft.method} onChange={(e) => set('method', e.target.value)} />
            </section>
          </>
        )}
      </div>
      <section className="kitchen">
        <h2>Notes</h2>
        <textarea className="page-area" aria-label="Notes" value={draft.notes} onChange={(e) => set('notes', e.target.value)} />
      </section>
      <section className="kitchen babble">
        <h2>
          Babette's babble <small>not printed</small>
        </h2>
        <textarea className="page-area" aria-label="Babette's babble" value={draft.context} onChange={(e) => set('context', e.target.value)} />
      </section>
    </article>
  )
}

export const NOTE_COLORS = ['rosewater', 'flamingo', 'pink', 'mauve', 'red', 'maroon', 'peach', 'yellow', 'green', 'teal', 'sky', 'sapphire', 'blue', 'lavender', 'none']

export function NotePage({ note, editing, draft, onDraft, onColor }) {
  return (
    <article className="page page-note" data-color={note.color || 'none'}>
      <header className="page-head">
        <p className="prov">{[note.type ? note.type[0].toUpperCase() + note.type.slice(1) : 'Note', dayOf(note.date)].filter(Boolean).join(', ')}</p>
      </header>
      {editing ? (
        <textarea className="note-edit" value={draft} onChange={(e) => onDraft(e.target.value)} aria-label="Note text" autoFocus />
      ) : (
        <Paragraphs className="note-body" text={note.text} />
      )}
      <div className="swatches" role="group" aria-label="Note colour">
        {NOTE_COLORS.map((c) => (
          <button key={c} type="button" data-color={c} aria-pressed={(note.color || 'none') === c} title={c} onClick={() => onColor(c)} />
        ))}
      </div>
    </article>
  )
}

export function ChatPage({ chat }) {
  const said = (chat.messages || []).filter((m) => m.role === 'user' || m.role === 'assistant')
  return (
    <article className="page page-chat">
      <header className="page-head">
        <p className="prov">{chatDate(chat)}</p>
      </header>
      <div className="chat-read">
        {said.map((m, i) => (
          <Message key={m.submission_id || i} message={m} />
        ))}
      </div>
    </article>
  )
}
