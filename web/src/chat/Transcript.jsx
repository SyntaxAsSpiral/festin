import { Fragment, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { fetchPlugins } from '../meals/plan.js'
import { useReducedMotion } from '../useReducedMotion.js'
import { InkReply } from './InkReply.jsx'
import { ListenControl } from './ListenControl.jsx'
import { voiceIsOn } from './listen.js'
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

// Trace steps under a reply. Thinking starts collapsed; while the reply is live,
// tool steps are open and each new step seeps onto the page as a whole (the
// letters' seep masks, larger pools), so traces arrive softly instead of popping.
function Trace({ steps, open }) {
  return (steps || []).map((step, i) => {
    const thinking = step.kind === 'thinking'
    const seep = open ? { '--mx': `${(i * 37) % 100}%`, '--my': `${(i * 61) % 100}%` } : undefined
    return (
      <details key={i} className={'chat-trace' + (open ? ' seep-in' : '')} style={seep} open={(open && !thinking) || undefined}>
        {thinking ? (
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
    )
  })
}

function Markdown({ text }) {
  return <div className="markdown-body" dangerouslySetInnerHTML={{ __html: renderChatMarkdown(text) }} />
}

function FileChip({ file }) {
  const name = file?.name || 'document'
  const href = file?.path
  if (href) {
    return (
      <a className="msg-file" href={href} target="_blank" rel="noreferrer">
        {name}
      </a>
    )
  }
  return <span className="msg-file">{name}</span>
}

export function Message({ message, live, body, voiceOn }) {
  const { role, content, photos, files, trace, stopped } = message
  const showListen =
    Boolean(voiceOn) && role === 'assistant' && !live && typeof content === 'string' && content.trim().length > 0
  return (
    <div className={'msg ' + (role === 'user' ? 'msg-you' : 'msg-babette') + (live ? ' msg-live' : '')}>
      {role === 'assistant' && stopped && <small className="stopped">Stopped</small>}
      {role === 'assistant' && <Trace steps={trace} open={live} />}
      {role === 'assistant' ? (
        body || (content && <Markdown text={content} />)
      ) : (
        <p>
          <Linked text={typeof content === 'string' ? content : ''} />
        </p>
      )}
      {showListen ? <ListenControl text={content} /> : null}
      {(photos || []).map((src) => (
        <img key={src} className="msg-photo" src={src} alt="A dish shared in conversation" />
      ))}
      {(files || []).map((file, i) => (
        <FileChip key={(file && file.path) || i} file={file} />
      ))}
    </div>
  )
}

export function Transcript({ messages, turn }) {
  const end = useRef(null)
  const navigate = useNavigate()
  const reduced = useReducedMotion()
  const [voiceOn, setVoiceOn] = useState(false)
  const sentId = turn.sent?.submissionId
  const stored = sentId && messages.some((m) => m.submission_id === sentId)
  const live = turn.phase === 'thinking' || turn.phase === 'revealing' || turn.phase === 'settled' || turn.phase === 'failed'
  const shownCount = Math.floor(turn.shown)

  useEffect(() => {
    let cancelled = false
    fetchPlugins().then((plugins) => {
      if (!cancelled) setVoiceOn(voiceIsOn(plugins))
    })
    return () => {
      cancelled = true
    }
  }, [messages.length])

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [messages.length, shownCount, turn.phase])

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
          <Message key={m.submission_id || i} message={m} voiceOn={voiceOn} />
        ))}
      {live && turn.sent && !stored && (
        <Message
          message={{
            role: 'user',
            content: turn.sent.text,
            photos: turn.sent.photos,
            files: turn.sent.files,
          }}
        />
      )}
      {/* One live reply from the first moment: trace steps seep in as they arrive
          while Babette thinks, then the text takes over the body. */}
      {(turn.phase === 'thinking' || turn.phase === 'revealing' || turn.phase === 'settled') && (
        <Message
          message={{ role: 'assistant', content: '', trace: turn.trace }}
          live
          voiceOn={voiceOn}
          body={
            turn.phase === 'thinking' ? (
              <p className="progress">{traceLine(turn.trace) || 'Babette is reading…'}</p>
            ) : (
              <InkReply text={turn.text} shown={shownCount} plain={reduced} />
            )
          }
        />
      )}
      <div ref={end} />
    </div>
  )
}
