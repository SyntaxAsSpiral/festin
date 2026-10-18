import { useCallback, useEffect, useState } from 'react'
import { bootKitchen, DEFAULT_TABLE_NAME } from './backend.js'

const RETRY_MS = 8000

export function useBoot() {
  const [phase, setPhase] = useState('boot')
  const [tableName, setTableName] = useState(DEFAULT_TABLE_NAME)
  const [attempt, setAttempt] = useState(0)

  const retry = useCallback(() => setAttempt((n) => n + 1), [])

  useEffect(() => {
    let gone = false
    bootKitchen().then(
      ({ tableName }) => {
        if (gone) return
        setTableName(tableName)
        setPhase('ready')
      },
      () => {
        if (gone) return
        setPhase('trouble')
      },
    )
    return () => {
      gone = true
    }
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
