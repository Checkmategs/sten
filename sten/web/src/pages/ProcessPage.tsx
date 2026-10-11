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

const PROCESSING_LINES = [
  'разбираю слова по слогам',
  'анализирую голос спикеров',
  'считаю паузы между предложениями',
]

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
  const [line, setLine] = useState(0)
  const [linePhase, setLinePhase] = useState<'in' | 'out'>('in')

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

  const showFlavor = status === 'processing' && !loadError && progress?.step !== 3
  const diarizing = status === 'processing' && !loadError && progress?.step === 3
  const percent = progress?.percent ?? 0

  useEffect(() => {
    if (!showFlavor) return
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const timer = window.setInterval(() => {
      if (reduce) {
        setLine((current) => (current + 1) % PROCESSING_LINES.length)
        return
      }
      setLinePhase('out')
    }, 3400)
    return () => window.clearInterval(timer)
  }, [showFlavor])

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
  const caption = diarizing
    ? progress?.label || 'Идёт разметка спикеров…'
    : showFlavor
    ? PROCESSING_LINES[line]
    : status === 'error'
      ? error || 'Не удалось обработать запись'
      : loadError
        ? loadError
        : status === 'recording'
          ? 'Сервер занят другой встречей'
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
          aria-valuenow={percent}
          aria-labelledby="process-status"
        >
          <svg viewBox="0 0 100 100" aria-hidden="true">
            <circle className="process-loader-track" cx="50" cy="50" r="42" />
            <circle className="process-loader-arc" cx="50" cy="50" r="42" />
          </svg>
          {showFlavor || diarizing ? (
            <span className="process-percent" aria-hidden="true">
              {percent}%
            </span>
          ) : null}
        </div>
        <p
          id="process-status"
          className={
            showFlavor
              ? linePhase === 'out'
                ? 'process-caption is-out'
                : 'process-caption is-in'
              : 'process-caption'
          }
          aria-live="polite"
          onAnimationEnd={(event) => {
            if (event.target !== event.currentTarget || event.animationName !== 'process-caption-out') {
              return
            }
            setLine((current) => (current + 1) % PROCESSING_LINES.length)
            setLinePhase('in')
          }}
        >
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
