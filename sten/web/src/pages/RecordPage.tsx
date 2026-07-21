import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  defaultMeetingTitle,
  formatElapsed,
  useRecorder,
} from '../useRecorder'

/** Recording screen for the facilitator: title, start/stop, level meter, timer. */
export function RecordPage() {
  const navigate = useNavigate()
  const [title, setTitle] = useState(() => defaultMeetingTitle())
  const { phase, elapsedMs, level, error, start, stop, isRecording, isBusy } =
    useRecorder()

  const handleStart = () => {
    const trimmed = title.trim() || defaultMeetingTitle()
    if (!title.trim()) setTitle(trimmed)
    void start(trimmed)
  }

  const handleStop = async () => {
    const id = await stop()
    if (id != null) navigate(`/m/${id}/process`)
  }

  const titleDisabled = phase !== 'idle'
  const startDisabled = phase !== 'idle' || isBusy
  const stopDisabled = !isRecording

  return (
    <main className="record-page">
      <p className="sten-brand">Sten</p>
      <h1>Запись встречи</h1>

      <label className="record-title-label" htmlFor="meeting-title">
        Название
      </label>
      <input
        id="meeting-title"
        className="record-title-input"
        type="text"
        value={title}
        disabled={titleDisabled}
        onChange={(e) => setTitle(e.target.value)}
        autoComplete="off"
      />

      <div className="record-status" aria-live="polite">
        <div className="record-timer" aria-label="Длительность записи">
          {formatElapsed(elapsedMs)}
        </div>
        <div className="record-level" aria-label="Уровень микрофона">
          <div
            className="record-level-fill"
            style={{ width: `${Math.min(100, Math.round(level * 100))}%` }}
          />
        </div>
        <p className="record-phase">
          {phase === 'idle' && 'Готово к записи'}
          {phase === 'starting' && 'Запуск…'}
          {phase === 'recording' && 'Идёт запись'}
          {phase === 'stopping' && 'Остановка…'}
        </p>
        {isRecording && level < 0.02 ? (
          <p className="record-hint" role="status">
            Уровень почти нулевой — проверьте микрофон (полоска выше должна
            прыгать, когда говорите).
          </p>
        ) : null}
        {isRecording && elapsedMs < 15_000 ? (
          <p className="record-hint">Запишите хотя бы 15–20 секунд с речью.</p>
        ) : null}
      </div>

      <div className="record-actions">
        {!isRecording && phase !== 'stopping' ? (
          <button
            type="button"
            className="record-btn record-btn-start"
            disabled={startDisabled}
            onClick={handleStart}
          >
            Начать запись
          </button>
        ) : (
          <button
            type="button"
            className="record-btn record-btn-stop"
            disabled={stopDisabled || elapsedMs < 5000}
            onClick={() => void handleStop()}
            title={
              elapsedMs < 5000 ? 'Подождите хотя бы 5 секунд' : undefined
            }
          >
            Стоп
          </button>
        )}
      </div>

      {error ? (
        <p className="record-error" role="alert">
          {error}
        </p>
      ) : null}
    </main>
  )
}
