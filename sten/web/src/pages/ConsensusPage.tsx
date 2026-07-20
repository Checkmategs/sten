import { Link, useParams } from 'react-router-dom'

/** Stub — full consensus UI in Task 6. */
export function ConsensusPage() {
  const { id } = useParams<{ id: string }>()

  return (
    <main>
      <h1>Consensus</h1>
      <p>
        Meeting <code>{id}</code> — consensus UI coming in Task 6.
      </p>
      <p>
        <Link to="/">Record</Link>
        {' · '}
        <Link to={`/m/${id}/process`}>Process stub</Link>
      </p>
    </main>
  )
}
