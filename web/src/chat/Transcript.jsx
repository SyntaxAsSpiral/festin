import { Fragment, useEffect, useRef } from 'react'
import { Link, useNavigate } from 'react-router'
import { renderChatMarkdown } from './markdown.js'
import { traceLine } from './turn.js'

const RECIPE_ID = /\b(CBK-\d{4,})\b/g

// Your messages are plain text, with CBK-#### turned into recipe links (as live).
function Linked({ text }) {
  return text.split(RECIPE_ID).map((part, i) =>
    i % 2 ? (
      <Link key={i} className="cbk" to={'/recipes/' + part}>
        {part}
      </Link>
    ) : (
      <Fragment key={i}>{part}</Fragment>
    ),
  )
}

// Live's trace summary and body for one tool step.
function toolSummary(step) {
  const args = step.args && typeof step.args === 'object' ? step.args : {}
  const result = step.result && typeof step.result === 'object' ? step.result : {}
  const bits = [step.label || step.name || 'Tool']
  if (args.query) bits.push(args.query)
  if (args.recipe_id) bits.push(args.recipe_id)
  if (args.title) bits.push(args.title)
  if (args.week_start) bits.push(args.week_start)
  if (/notes/.test(step.label || '') && result.count != null) bits.push(result.count + ' notes')
  if (result.status) bits.push(result.status)
  if (result.error) bits.push('could not finish')
  return bits.join(' · ')
}

function toolBody(step) {
  const result = step.result && typeof step.result === 'object' ? step.result : {}
  if (result.error) return result.error
  if (result.titles?.length) return result.titles.join('\n')
  if (result.message) return result.message
  if (result.count != null) return result.count + ' found'
  return ''
}

function Trace({ steps, open }) {
  return (steps || []).map((step, i) => (
    <details key={i} className="chat-trace" open={open || undefined}>
      {step.kind === 'thinking' ? (
        <>
          <summary>Thinking</summary>
          <div className="trace-thinking">{step.text || ''}</div>
        </>
      ) : (
        <>
          <summary>{toolSummary(step)}</summary>
          {toolBody(step) && <div className="trace-tool">{toolBody(step)}</div>}
        </>
      )}
    </details>
  ))
}

function Markdown({ text }) {
  return <div className="markdown-body" dangerouslySetInnerHTML={{ __html: renderChatMarkdown(text) }} />
}

function Message({ message, live }) {
  const { role, content, photos, trace, stopped } = message
  return (
    <div className={'msg ' + (role === 'user' ? 'msg-you' : 'msg-babette') + (live ? ' msg-live' : '')}>
      {role === 'assistant' && stopped && <small className="stopped">Stopped</small>}
      {role === 'assistant' && <Trace steps={trace} open={live} />}
      {role === 'assistant' ? (
        content && <Markdown text={content} />
      ) : (
        <p>
          <Linked text={typeof content === 'string' ? content : ''} />
        </p>
      )}
      {(photos || []).map((src) => (
        <img key={src} className="msg-photo" src={src} alt="A dish shared in conversation" />
      ))}
    </div>
  )
}

export function Transcript({ messages, turn }) {
  const end = useRef(null)
  const navigate = useNavigate()
  const sentId = turn.sent?.submissionId
  const stored = sentId && messages.some((m) => m.submission_id === sentId)
  const live = turn.phase === 'thinking' || turn.phase === 'revealing' || turn.phase === 'settled' || turn.phase === 'failed'
  const shown = turn.text.slice(0, Math.floor(turn.shown))

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [messages.length, shown.length, turn.phase])

  // Recipe links inside rendered Markdown route in-app instead of reloading.
  function onClick(event) {
    const link = event.target.closest?.('a[data-recipe]')
    if (!link || event.metaKey || event.ctrlKey || event.shiftKey) return
    event.preventDefault()
    navigate('/recipes/' + link.dataset.recipe)
  }

  return (
    <div className="transcript" aria-live="polite" onClick={onClick}>
      {messages
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .map((m, i) => (
          <Message key={m.submission_id || i} message={m} />
        ))}
      {live && turn.sent && !stored && <Message message={{ role: 'user', content: turn.sent.text }} />}
      {turn.phase === 'thinking' && <p className="progress">{traceLine(turn.trace) || 'Babette is reading…'}</p>}
      {(turn.phase === 'revealing' || turn.phase === 'settled') && (
        <Message message={{ role: 'assistant', content: shown, trace: turn.trace }} live />
      )}
      <div ref={end} />
    </div>
  )
}
