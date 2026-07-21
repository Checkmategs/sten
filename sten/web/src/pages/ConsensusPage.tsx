import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  api,
  type Item,
  type MeetingDetail,
  type TranscriptTurn,
} from '../api'
import { ItemCard } from '../components/ItemCard'

const CATEGORY_LABELS: Record<string, string> = {
  decision: 'Решение',
  task: 'Задача',
  topic: 'Контекст',
  question: 'Открытый вопрос',
}

type Tab = 'consensus' | 'transcript'

function formatTs(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${m}:${r.toString().padStart(2, '0')}`
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
  const [tab, setTab] = useState<Tab>('consensus')
  const [transcriptText, setTranscriptText] = useState<string | null>(null)
  const [turns, setTurns] = useState<TranscriptTurn[]>([])
  const [diarized, setDiarized] = useState(false)
  const [diarizeBusy, setDiarizeBusy] = useState(false)
  const [transcriptError, setTranscriptError] = useState<string | null>(null)
  const [transcriptLoading, setTranscriptLoading] = useState(false)

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

  const loadTranscript = useCallback(async () => {
    setTranscriptLoading(true)
    try {
      const res = await api.getTranscript(meetingId)
      setTranscriptText(res.text)
      setTurns(res.turns)
      setDiarized(res.diarized)
      setDiarizeBusy(res.busy)
      setTranscriptError(res.error)
    } catch (err) {
      setTranscriptError(err instanceof Error ? err.message : String(err))
    } finally {
      setTranscriptLoading(false)
    }
  }, [meetingId])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (tab !== 'transcript') return
    void loadTranscript()
  }, [tab, loadTranscript])

  useEffect(() => {
    if (tab !== 'transcript' || !diarizeBusy) return
    const timer = window.setInterval(() => void loadTranscript(), 2000)
    return () => window.clearInterval(timer)
  }, [tab, diarizeBusy, loadTranscript])

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

  const handleDiarize = async () => {
    setTranscriptError(null)
    setDiarizeBusy(true)
    try {
      await api.diarize(meetingId)
      void loadTranscript()
    } catch (err) {
      setTranscriptError(err instanceof Error ? err.message : String(err))
      setDiarizeBusy(false)
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
      <p className="sten-brand">Sten</p>
      <header className="consensus-header">
        <h1>{meeting.title}</h1>
        <p className="consensus-progress" aria-live="polite">
          Принято {accepted} из {total}
        </p>
      </header>

      <div className="consensus-tabs" role="tablist" aria-label="Разделы">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'consensus'}
          className={`consensus-tab${tab === 'consensus' ? ' consensus-tab-active' : ''}`}
          onClick={() => setTab('consensus')}
        >
          Согласование
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'transcript'}
          className={`consensus-tab${tab === 'transcript' ? ' consensus-tab-active' : ''}`}
          onClick={() => setTab('transcript')}
        >
          Текст встречи
        </button>
      </div>

      {tab === 'transcript' ? (
        <section className="transcript-panel" aria-label="Текст встречи">
          <div className="transcript-toolbar">
            {!diarized ? (
              <button
                type="button"
                className="consensus-btn-secondary"
                disabled={diarizeBusy || transcriptLoading}
                onClick={() => void handleDiarize()}
              >
                {diarizeBusy ? 'Размечаю спикеров…' : 'Разметить спикеров'}
              </button>
            ) : (
              <p className="transcript-meta">Размечено по голосам</p>
            )}
          </div>

          {transcriptLoading && transcriptText == null ? (
            <p className="transcript-empty">Загрузка транскрипта…</p>
          ) : null}
          {transcriptError ? (
            <p className="consensus-error" role="alert">
              {transcriptError}
            </p>
          ) : null}

          {!transcriptLoading || transcriptText != null ? (
            diarized && turns.length > 0 ? (
              <ol className="transcript-turns">
                {turns.map((turn, i) => (
                  <li key={`${turn.start}-${i}`} className="transcript-turn">
                    <div className="transcript-turn-head">
                      <span className="transcript-speaker">{turn.speaker}</span>
                      <span className="transcript-time">
                        {formatTs(turn.start)}
                      </span>
                    </div>
                    <p className="transcript-turn-text">{turn.text}</p>
                  </li>
                ))}
              </ol>
            ) : transcriptText?.trim() ? (
              <pre className="transcript-text">{transcriptText}</pre>
            ) : (
              <p className="transcript-empty">
                Транскрипт ещё не готов или пуст.
              </p>
            )
          ) : null}
        </section>
      ) : (
        <>
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
        </>
      )}
    </main>
  )
}
