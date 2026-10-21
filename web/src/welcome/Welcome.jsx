import { useEffect, useRef, useState } from 'react'
import { hasSeenWelcome, markWelcomeSeen, WELCOME_EVENT } from './welcome.js'
import './welcome.css'

const PIECES = [
  ['The Cookbook', 'Every recipe is a card. A formule says what goes in; a praxis says how it is done, like a technique. Ask me to add, edit, search or delete cards. I always search first, so we never end up with five pot roasts.'],
  ['The Dinner Week', 'Saturday through Friday, seven nights, and blank nights are welcome. Tell me what is for dinner and I will save the plan, and print a slip of it if you like.'],
  ['Notes', 'Shopping lists, tasks and reminders, colour-coded and pinnable. Lasting facts about the household (who lives here, allergies, what nobody eats) go somewhere more permanent, so I never forget them.'],
  ['The Kitchen Log', 'Every change, cook and note is dated. Ask me when you last made borscht and I will find out. When you make a dish, or send me a photo of it, I mark the card cooked, clear it from the to-cook queue and add a line to your history. Over time the cookbook learns what this house actually makes, not just what sounds nice.'],
]

const TRY = [
  ['What is for dinner this week?', 'I show the plan.'],
  ['Add my grandmother’s apple cake.', 'I look for a match first, then make the card.'],
  ['We made the chili last night and it was great.', 'I mark it cooked, and heart it if you loved it.'],
  ['Print the dinner plan.', 'I preview a slip, check with you, then print.'],
]

// First run: Babette introduces herself, once per device.
export function Welcome() {
  const [open, setOpen] = useState(() => !hasSeenWelcome())
  const dialog = useRef(null)

  useEffect(() => {
    const again = () => setOpen(true)
    window.addEventListener(WELCOME_EVENT, again)
    return () => window.removeEventListener(WELCOME_EVENT, again)
  }, [])

  useEffect(() => {
    if (!open) return undefined
    dialog.current?.focus({ preventScroll: true })
    const onKey = (event) => {
      if (event.key === 'Escape') close()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  function close() {
    markWelcomeSeen()
    setOpen(false)
  }

  if (!open) return null
  return (
    <div className="welcome-scrim" onClick={(event) => event.target === event.currentTarget && close()}>
      <div className="welcome" role="dialog" aria-modal="true" aria-labelledby="welcome-title" tabIndex={-1} ref={dialog}>
        <h2 id="welcome-title">Bonjour. I&rsquo;m Babette.</h2>
        <p className="welcome-lede">
          I keep the kitchen: the cookbook, the week&rsquo;s dinners, your notes and the printer. You talk like a person, and I keep the ledger.
        </p>
        <dl className="welcome-pieces">
          {PIECES.map(([name, text]) => (
            <div key={name}>
              <dt>{name}</dt>
              <dd>{text}</dd>
            </div>
          ))}
        </dl>
        <h3>To begin</h3>
        <ul className="welcome-try">
          {TRY.map(([say, does]) => (
            <li key={say}>
              <q>{say}</q> {does}
            </li>
          ))}
        </ul>
        <div className="welcome-foot">
          <button type="button" onClick={close}>Got it</button>
        </div>
      </div>
    </div>
  )
}
