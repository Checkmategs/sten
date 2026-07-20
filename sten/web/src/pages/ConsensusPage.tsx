import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, type Item, type MeetingDetail } from '../api'
import { ItemCard } from '../components/ItemCard'

const CATEGORY_ORDER: { key: string; title: string }[] = [
  { key: 'decision', title: 'Решения' },
  { key: 'task', title: 'Задачи' },
  { key: 'topic', title: 'Темы' },
  { key: 'question', title: 'Открытые вопросы' },
]

function groupItems(items: Item[]): { title: string; items: Item[] }[] {
  const groups: { title: string; items: Item[] }[] = []
  for (const { key, title } of CATEGORY_ORDER) {
    const matching = items.filter((i) => i.category === key)
    if (matching.length > 0) groups.push({ title, items: matching })
  }
  const known = new Set(CATEGORY_ORDER.map((c) => c.key))
  const other = items.filter((i) => !known.has(i.category))
  if (other.length > 0) groups.push({ title: 'Прочее', items: other })
  return groups
}

/** Live consensus screen for TV: accept, edit, rewrite summary items. */
export function ConsensusPage() {
  const { id } = useParams<{ id: string }>()
  const meetingId = Number(id)

  const [meeting, setMeeting] = useState<MeetingDetail | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!Number.isFinite(meetingId) || meetingId <= 0) {
      setLoadError('Некорректный идентификатор встречи')
      return
    }
    try {
      const data = await api.getMeeting(meetingId)
      setMeeting(data)
      setLoadError(null)
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err))
    }
  }, [meetingId])

  useEffect(() => {
    void load()
  }, [load])

  if (loadError && !meeting) {
    return (
      <main className="consensus-page">
        <p className="consensus-error" role="alert">
          {loadError}
        </p>
      </main>
    )
  }

  if (!meeting) {
    return (
      <main className="consensus-page">
        <p className="consensus-loading">Загрузка…</p>
      </main>
    )
  }

  const accepted = meeting.counts.accepted ?? 0
  const pending = meeting.counts.pending ?? 0
  const total = accepted + pending
  const allAccepted =
    meeting.status === 'consensus' || (total > 0 && pending === 0)
  const groups = groupItems(meeting.items)

  return (
    <main className="consensus-page">
      <header className="consensus-header">
        <h1>{meeting.title}</h1>
        <p className="consensus-progress" aria-live="polite">
          Принято {accepted} из {total}
        </p>
      </header>

      {allAccepted ? (
        <div className="consensus-banner" role="status">
          Протокол согласован
        </div>
      ) : null}

      {loadError ? (
        <p className="consensus-error" role="alert">
          {loadError}
        </p>
      ) : null}

      {groups.length === 0 ? (
        <p className="consensus-empty">Нет пунктов для согласования.</p>
      ) : (
        groups.map((group) => (
          <section key={group.title} className="consensus-section">
            <h2>{group.title}</h2>
            <ul className="consensus-list">
              {group.items.map((item) => (
                <li key={item.id}>
                  <ItemCard
                    meetingId={meetingId}
                    item={item}
                    onChanged={() => void load()}
                  />
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </main>
  )
}
