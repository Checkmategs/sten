import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, type Item, type MeetingDetail } from '../api'
import { ItemCard } from '../components/ItemCard'

const CATEGORY_LABELS: Record<string, string> = {
  decision: 'Решение',
  task: 'Задача',
  topic: 'Контекст',
  question: 'Открытый вопрос',
}

function groupByTheme(items: Item[]): { title: string; items: Item[] }[] {
  const order: string[] = []
  const map = new Map<string, Item[]>()
  for (const item of items) {
    const theme = item.theme?.trim() || 'Общее'
    if (!map.has(theme)) {
      map.set(theme, [])
      order.push(theme)
    }
    map.get(theme)!.push(item)
  }
  return order.map((title) => ({ title, items: map.get(title)! }))
}

/** Live consensus screen for TV: accept, edit, rewrite summary items. */
export function ConsensusPage() {
  const { id } = useParams<{ id: string }>()
  const meetingId = Number(id)
  const navigate = useNavigate()

  const [meeting, setMeeting] = useState<MeetingDetail | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [resummarizing, setResummarizing] = useState(false)

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

  const handleResummarize = async () => {
    setResummarizing(true)
    setLoadError(null)
    try {
      await api.resummarize(meetingId)
      navigate(`/m/${meetingId}/process`, { replace: true })
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err))
      setResummarizing(false)
    }
  }

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
  const allAccepted = total > 0 && pending === 0
  const groups = groupByTheme(meeting.items)

  return (
    <main className="consensus-page">
      <header className="consensus-header">
        <h1>{meeting.title}</h1>
        <p className="consensus-progress" aria-live="polite">
          Принято {accepted} из {total}
        </p>
        <p className="consensus-actions">
          <button
            type="button"
            className="consensus-btn-secondary"
            disabled={resummarizing}
            onClick={() => void handleResummarize()}
          >
            {resummarizing ? 'Пересборка…' : 'Пересобрать выводы'}
          </button>
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
        <div className="consensus-empty">
          <p>Нет пунктов для согласования.</p>
          <p>
            Обычно так бывает, если в записи не было речи или выбран не тот
            микрофон. Запишите ещё раз подольше — с голосом в кадре.
          </p>
          <p>
            <Link to="/">Новая запись</Link>
          </p>
        </div>
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
                    categoryLabel={
                      CATEGORY_LABELS[item.category] ?? item.category
                    }
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
