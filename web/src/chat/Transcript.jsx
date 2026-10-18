import { Fragment, useEffect, useRef } from 'react'
import { Link } from 'react-router'
import { traceLine } from './turn.js'

const RECIPE_ID = /\b(CBK-\d{4,})\b/g

// Plain text with CBK-#### turned into links to the recipe's card.
function Linked({ text }) {
  const parts = text.split(RECIPE_ID)
  return parts.map((part, i) =>
    i % 2 ? (
      <Link key={i} className="cbk" to={'/recipes/' + part}>
        {part}
      </Link>
    ) : (
      <Fragment key={i}>{part}</Fragment>
    ),
  )
}

function Body({ text }) {
  return text
    .split(/\n{2,}/)
    .filter((para) => para.trim())
    .map((para, i) => (
      <p key={i}>
        <Linked text={para} />
      </p>
    ))
}

function Message({ role, content, photos }) {
  return (
    <div className={'msg ' + (role === 'user' ? 'msg-you' : 'msg-babette')}>
      {(photos || []).map((src) => (
        <img key={src} className="msg-photo" src={src} alt="A dish shared in conversation" />
      ))}
      <Body text={typeof content === 'string' ? content : ''} />
    </div>
  )
}

export function Transcript({ messages, turn }) {
  const end = useRef(null)
  const sentId = turn.sent?.submissionId
  const stored = sentId && messages.some((m) => m.submission_id === sentId)
  const live = turn.phase === 'thinking' || turn.phase === 'revealing' || turn.phase === 'settled' || turn.phase === 'failed'
  const shown = turn.text.slice(0, Math.floor(turn.shown))

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [messages.length, shown.length, turn.phase])

  return (
    <div className="transcript" aria-live="polite">
      {messages
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .map((m, i) => (
          <Message key={m.submission_id || i} role={m.role} content={m.content} photos={m.photos} />
        ))}
      {live && turn.sent && !stored && <Message role="user" content={turn.sent.text} />}
      {turn.phase === 'thinking' && <p className="progress">{traceLine(turn.trace) || 'Babette is reading…'}</p>}
      {(turn.phase === 'revealing' || turn.phase === 'settled') && (
        <div className="msg msg-babette msg-live">
          <Body text={shown} />
          {turn.phase === 'revealing' && traceLine(turn.trace) && <p className="progress">{traceLine(turn.trace)}</p>}
        </div>
      )}
      <div ref={end} />
    </div>
  )
}
