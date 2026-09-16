import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, type MeetingStatus } from '../api'

const STATUS_LABELS: Record<MeetingStatus, string> = {
  recording: 'Запись',
  processing: 'Обработка…',
  ready: 'Готово',
  consensus: 'Протокол согласован',
  error: 'Ошибка',
}

/** Polls meeting processing status and routes to consensus when ready. */
export function ProcessPage() {
  const { id } = useParams<{ id: string }>()
  const meetingId = Number(id)
  const navigate = useNavigate()

  const [status, setStatus] = useState<MeetingStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  const poll = useCallback(async () => {
    if (!Number.isFinite(meetingId) || meetingId <= 0) {
      setLoadError('Некорректный идентификатор встречи')
      return
    }
    try {
      const res = await api.getStatus(meetingId)
      setStatus(res.status)
      setError(res.error)
      setLoadError(null)
      if (res.status === 'ready' || res.status === 'consensus') {
        navigate(`/m/${meetingId}/consensus`, { replace: true })
      }
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err))
    }
  }, [meetingId, navigate])

  useEffect(() => {
    void poll()
    const timer = window.setInterval(() => void poll(), 2000)
    return () => window.clearInterval(timer)
  }, [poll])

  const handleRetry = async () => {
    setBusy(true)
    setLoadError(null)
    try {
      await api.stopMeeting(meetingId)
      setStatus('processing')
      setError(null)
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const label =
    status != null ? STATUS_LABELS[status] : loadError ? null : 'Загрузка…'

  return (
    <main className="process-page">
      <h1>Обработка встречи</h1>

      {label ? (
        <p className="process-status" aria-live="polite">
          {label}
        </p>
      ) : null}

      {status === 'error' ? (
        <div className="process-error" role="alert">
          <p>{error || 'Не удалось обработать запись'}</p>
          <button
            type="button"
            className="process-btn"
            disabled={busy}
            onClick={() => void handleRetry()}
          >
            Повторить
          </button>
        </div>
      ) : null}

      {loadError && status !== 'error' ? (
        <p className="process-error" role="alert">
          {loadError}
        </p>
      ) : null}
    </main>
  )
}
