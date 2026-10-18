import { useCallback, useEffect, useState } from 'react'
import { DEFAULT_TABLE_NAME, fetchTableName } from './table.js'

const RETRY_MS = 8000

export function useBoot() {
  const [phase, setPhase] = useState('boot')
  const [tableName, setTableName] = useState(DEFAULT_TABLE_NAME)
  const [attempt, setAttempt] = useState(0)

  const retry = useCallback(() => setAttempt((n) => n + 1), [])

  useEffect(() => {
    const ac = new AbortController()
    fetchTableName(ac.signal).then(
      (name) => {
        setTableName(name)
        setPhase('ready')
      },
      (err) => {
        if (ac.signal.aborted || err?.name === 'AbortError') return
        setPhase('trouble')
      },
    )
    return () => ac.abort()
  }, [attempt])

  useEffect(() => {
    if (phase !== 'trouble') return undefined
    const id = setInterval(() => setAttempt((n) => n + 1), RETRY_MS)
    return () => clearInterval(id)
  }, [phase])

  useEffect(() => {
    document.title = tableName
  }, [tableName])

  return { phase, tableName, retry }
}
