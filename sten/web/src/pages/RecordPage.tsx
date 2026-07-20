import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'

/** Stub — full recording UI in Task 5. */
export function RecordPage() {
  const [health, setHealth] = useState<string>('…')

  useEffect(() => {
    let cancelled = false
    api
      .health()
      .then((r) => {
        if (!cancelled) setHealth(r.ok ? 'ok' : 'not ok')
      })
      .catch((err: unknown) => {
        if (!cancelled) setHealth(err instanceof Error ? err.message : String(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <main>
      <h1>Record</h1>
      <p>Recording UI — coming in Task 5.</p>
      <p>
        API health: <code>{health}</code>
      </p>
      <p>
        <Link to="/m/1/process">Process stub</Link>
        {' · '}
        <Link to="/m/1/consensus">Consensus stub</Link>
      </p>
    </main>
  )
}
