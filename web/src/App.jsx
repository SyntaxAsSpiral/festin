import { BrowserRouter } from 'react-router'
import { Shell } from './Shell.jsx'
import { useBoot } from './useBoot.js'

function BootScreen() {
  return (
    <div className="boot" data-app="boot">
      <p>Setting the table…</p>
    </div>
  )
}

export function App() {
  const boot = useBoot()
  return (
    <BrowserRouter>
      {boot.phase === 'boot' ? <BootScreen /> : <Shell boot={boot} />}
    </BrowserRouter>
  )
}
