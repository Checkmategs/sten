import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, type MeetingStatus, type ProcessProgress } from '../api'

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
  const headingRef = useRef<HTMLHeadingElement>(null)

  const [status, setStatus] = useState<MeetingStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState<ProcessProgress | null>(null)
  const [busy, setBusy] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    headingRef.current?.focus()
  }, [])

  const poll = useCallback(async () => {
    if (!Number.isFinite(meetingId) || meetingId <= 0) {
      setLoadError('Некорректный идентификатор встречи')
      return
    }
    try {
      const res = await api.getStatus(meetingId)
      setStatus(res.status)
      setError(res.error)
      setProgress(res.progress)
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

  const failed = status === 'error' || Boolean(loadError)
  const caption =
    status === 'error'
      ? error || 'Не удалось обработать запись'
      : loadError
        ? loadError
        : status === 'recording'
          ? 'Сервер занят другой встречей'
          : progress?.label
            ? progress.label
            : status != null
              ? STATUS_LABELS[status]
              : 'Загрузка…'

  return (
    <main className="process-page">
      <h1 ref={headingRef} className="visually-hidden" tabIndex={-1}>
        Обработка встречи
      </h1>
      <div className="process-stage">
        <div
          className={failed ? 'process-loader is-still' : 'process-loader'}
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress?.percent ?? 0}
          aria-labelledby="process-status"
        >
          <svg viewBox="0 0 100 100" aria-hidden="true">
            <circle className="process-loader-track" cx="50" cy="50" r="42" />
            <circle className="process-loader-arc" cx="50" cy="50" r="42" />
          </svg>
        </div>
        <p id="process-status" className="process-caption" aria-live="polite">
          {caption}
        </p>
        {status === 'error' || status === 'recording' ? (
          <button
            type="button"
            className="process-retry"
            disabled={busy}
            onClick={() => void handleRetry()}
          >
            {status === 'recording' ? 'Начать обработку' : 'Повторить'}
          </button>
        ) : null}
      </div>
    </main>
  )
}
