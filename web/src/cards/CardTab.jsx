import { useState } from 'react'
import { useParams } from 'react-router'
import { CardOverlay } from './CardOverlay.jsx'
import { Collection } from './Collection.jsx'
import './cards.css'

// A card tab: its list, and the open card over it when the URL names one.
export function CardTab({ kind }) {
  const rest = useParams()['*'] || ''
  const id = decodeURIComponent(rest.split('/')[0] || '')
  const [revision, setRevision] = useState(0)
  return (
    <>
      <Collection kind={kind} cardOpen={Boolean(id)} revision={revision} />
      {id && <CardOverlay key={id} kind={kind} id={id} onChanged={() => setRevision((n) => n + 1)} />}
    </>
  )
}
