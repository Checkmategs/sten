import { Link, useParams } from 'react-router-dom'

/** Stub — full processing UI in Task 6. */
export function ProcessPage() {
  const { id } = useParams<{ id: string }>()

  return (
    <main>
      <h1>Process</h1>
      <p>
        Meeting <code>{id}</code> — processing status UI coming in Task 6.
      </p>
      <p>
        <Link to="/">Record</Link>
        {' · '}
        <Link to={`/m/${id}/consensus`}>Consensus stub</Link>
      </p>
    </main>
  )
}
