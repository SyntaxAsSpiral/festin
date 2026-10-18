import { useState } from 'react'
import { Message } from '../chat/Transcript.jsx'
import { chatDate, dayOf, plateFor, provenance } from './kinds.js'

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

export function RecipePage({ recipe }) {
  const [scanOpen, setScanOpen] = useState(false)
  const scan = served((recipe.ocrPhotos || [])[0])
  const photos = (recipe.photos || []).map(served)
  const ingredients = Array.isArray(recipe.ingredients) ? recipe.ingredients : []
  const kitchen = [recipe.notes, recipe.context].filter((t) => String(t || '').trim())
  return (
    <article className="page page-recipe">
      <img className="frontis" src={plateFor(recipe.category)} alt="" />
      <header className="page-head">
        <h1>{recipe.title}</h1>
        <p className="prov">{provenance(recipe)}</p>
      </header>
      {recipe.searchDescription && <p className="standfirst">{recipe.searchDescription}</p>}
      <div className="recipe-body">
        {scan && (
          <figure className="from-box">
            <button type="button" onClick={() => setScanOpen(true)} aria-label="Open the original card">
              <img src={scan} alt={'The original card for ' + recipe.title} loading="lazy" />
            </button>
            <figcaption>From the box</figcaption>
          </figure>
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
        {recipe.method && (
          <section className="method">
            <h2>Method</h2>
            <Paragraphs text={recipe.method} />
          </section>
        )}
        {!ingredients.length && !recipe.method && <p className="quiet">This card has no ingredients or method yet.</p>}
      </div>
      {photos.length > 0 && (
        <div className="cooked-photos">
          {photos.map((src) => (
            <img key={src} src={src} alt={'Cooked: ' + recipe.title} loading="lazy" />
          ))}
        </div>
      )}
      {kitchen.length > 0 && (
        <section className="kitchen">
          <p className="fleuron" aria-hidden="true">
            ❦
          </p>
          <h2>In the kitchen</h2>
          {kitchen.map((t, i) => (
            <Paragraphs key={i} text={t} />
          ))}
        </section>
      )}
      {scanOpen && (
        <button type="button" className="scan-full" onClick={() => setScanOpen(false)} aria-label="Close the original card">
          <img src={scan} alt={'The original card for ' + recipe.title} />
        </button>
      )}
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
