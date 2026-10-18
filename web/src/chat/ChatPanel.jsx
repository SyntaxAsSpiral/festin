import { Composer } from './Composer.jsx'
import { Transcript } from './Transcript.jsx'
import './chat.css'

// What goes inside the chat surface: the transcript and the composer.
export function ChatPanel({ chat }) {
  if (!chat.ready) return <p className="progress">Setting the table…</p>
  return (
    <div className="chat-panel">
      <Transcript messages={chat.messages} turn={chat.turn} />
      <Composer chat={chat} />
    </div>
  )
}

// The last line of the real conversation, for the tucked strip.
export function peekLine(chat) {
  const { turn } = chat
  if (turn.phase === 'thinking') return 'Babette is reading…'
  if (turn.phase === 'revealing' || turn.phase === 'settled') return lastLine(turn.text.slice(0, Math.floor(turn.shown)))
  const last = [...chat.messages].reverse().find((m) => m.role === 'user' || m.role === 'assistant')
  return last ? lastLine(last.content) : ''
}

function lastLine(text) {
  const lines = String(text || '').split('\n').map((l) => l.trim()).filter(Boolean)
  return lines.length ? lines[lines.length - 1] : ''
}

export function chatHeader(chat) {
  return chat.model ? chat.model + (chat.host ? ' · ' + chat.host : '') : ''
}
