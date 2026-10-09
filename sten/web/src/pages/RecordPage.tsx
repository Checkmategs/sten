import { useEffect, useRef, useState, type ChangeEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { SoundWave } from '../components/SoundWave'
import {
  defaultMeetingTitle,
  formatElapsed,
  httpsAppUrl,
  useRecorder,
} from '../useRecorder'

const MAX_UPLOAD_BYTES = 512 * 1024 * 1024
const ACCEPT =
  'audio/*,video/mp4,.m4a,.caf,.mp3,.wav,.ogg,.webm,.aac,.flac,.mp4,.mpeg,.m4b'
const ALLOWED_EXTS = new Set([
  'webm',
  'm4a',
  'caf',
  'mp3',
  'wav',
  'ogg',
  'oga',
  'aac',
  'flac',
  'mp4',
  'mpeg',
  'mpga',
  'm4b',
])

const HERO_PHRASES = [
  'Sten зафиксирует',
  'Sten прослушает',
  'Sten обработает',
]

function useHeroTypewriter(active: boolean): string {
  const [text, setText] = useState('')

  useEffect(() => {
    if (!active) return
    let cancelled = false
    let timer = 0
    const sleep = (ms: number) =>
      new Promise<void>((resolve) => {
        timer = window.setTimeout(resolve, ms)
      })
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    let index = 0

    const run = async () => {
      while (!cancelled) {
        const full = HERO_PHRASES[index % HERO_PHRASES.length]
        index += 1
        if (reduce) {
          setText(full)
          await sleep(4200)
          continue
        }
        setText('')
        for (let i = 1; i <= full.length && !cancelled; i += 1) {
          setText(full.slice(0, i))
          await sleep(72 + Math.random() * 48)
        }
        if (cancelled) break
        await sleep(3400)
        for (let i = full.length; i >= 0 && !cancelled; i -= 1) {
          setText(full.slice(0, i))
          await sleep(36)
        }
        if (cancelled) break
        await sleep(520)
      }
    }
    void run()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [active])

  return text
}

function fileLooksUnsupported(file: File): boolean {
  const name = file.name.toLowerCase()
  const dot = name.lastIndexOf('.')
  const ext = dot >= 0 ? name.slice(dot + 1) : ''
  if (ext && ALLOWED_EXTS.has(ext)) return false
  if (file.type.startsWith('audio/') || file.type === 'video/mp4') return false
  return Boolean(ext)
}

/** Recording screen: live mic or file upload, then process page. */
export function RecordPage() {
  const navigate = useNavigate()
  const { phase, elapsedMs, waveSamples, error, start, stop, isRecording, isBusy } =
    useRecorder()
  const startBtnRef = useRef<HTMLButtonElement>(null)
  const stopBtnRef = useRef<HTMLButtonElement>(null)
  const uploadLabelRef = useRef<HTMLLabelElement>(null)
  const prevPhaseRef = useRef(phase)

  const [uploadPhase, setUploadPhase] = useState<'idle' | 'uploading'>('idle')
  const [uploadRatio, setUploadRatio] = useState(0)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const handleStart = () => {
    void start(defaultMeetingTitle())
  }

  const handleStop = async () => {
    const id = await stop()
    if (id != null) navigate(`/m/${id}/process`)
  }

  const handleFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return

    if (file.size === 0) {
      setUploadError('Файл пустой. Выберите аудиозапись.')
      return
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setUploadError('Файл больше 512 МБ.')
      return
    }
    if (fileLooksUnsupported(file)) {
      setUploadError(
        'Неподдерживаемый формат. Загрузите аудио (m4a, caf, mp3, wav, webm и т.д.).',
      )
      return
    }

    const trimmed = defaultMeetingTitle()
    setUploadError(null)
    setUploadRatio(0)
    setUploadPhase('uploading')

    let createdId: number | null = null
    try {
      const meeting = await api.createMeeting(trimmed)
      createdId = meeting.id
      await api.uploadMeetingAudio(meeting.id, file, (ratio) => {
        setUploadRatio(ratio)
      })
      setUploadRatio(1)
      navigate(`/m/${meeting.id}/process`)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      if (createdId != null && /API 409\b/.test(msg)) {
        navigate(`/m/${createdId}/process`)
        return
      }
      setUploadError(`Не удалось загрузить файл: ${msg}`)
      setUploadPhase('idle')
    }
  }

  useEffect(() => {
    const prev = prevPhaseRef.current
    prevPhaseRef.current = phase
    if (phase === 'recording' && prev !== 'recording') {
      stopBtnRef.current?.focus()
    }
    if (phase === 'idle' && prev === 'starting' && error) {
      startBtnRef.current?.focus()
    }
  }, [phase, error])

  useEffect(() => {
    if (uploadError) uploadLabelRef.current?.focus()
  }, [uploadError])

  const insecure = typeof window !== 'undefined' && !window.isSecureContext
  const uploading = uploadPhase === 'uploading'
  const startDisabled = phase !== 'idle' || isBusy || insecure || uploading
  const uploadDisabled = phase !== 'idle' || isBusy || uploading
  const stopTooSoon = isRecording && elapsedMs < 5000
  const uploadPercent = Math.min(100, Math.round(uploadRatio * 100))
  const atStart = phase === 'idle' && !uploading
  const heroText = useHeroTypewriter(atStart)

  return (
    <main className="record-page record-home" aria-busy={uploading}>
      <div className="record-hero">
        {atStart ? (
          <>
            <h1 className="record-hero-title" aria-live="off">
              <span className="record-hero-live">
                <span>{heroText}</span>
                <span className="record-hero-caret" aria-hidden="true" />
              </span>
            </h1>
            <p className="record-hero-sub">начните запись или загрузите файл</p>
          </>
        ) : (
          <h1 className="visually-hidden">Запись встречи</h1>
        )}

        {uploading ? (
          <div className="record-status">
            <p className="record-phase">
              <span id="upload-status" role="status">
                Загрузка файла…
              </span>{' '}
              <span aria-hidden="true">{uploadPercent}%</span>
            </p>
            <div
              className="record-progress"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={uploadPercent}
              aria-labelledby="upload-status"
            >
              <div
                className="record-progress-fill"
                style={{ width: `${uploadPercent}%` }}
                aria-hidden="true"
              />
            </div>
          </div>
        ) : !atStart ? (
          <div className="record-status">
            <div
              className="record-timer"
              role="timer"
              aria-live="off"
              aria-label="Длительность записи"
            >
              {formatElapsed(elapsedMs)}
            </div>
            <SoundWave samplesRef={waveSamples} />
          </div>
        ) : null}

        <div className="record-actions">
          {!isRecording && phase !== 'stopping' && !uploading ? (
            <>
              <button
                ref={startBtnRef}
                type="button"
                className="record-btn record-btn-start"
                disabled={startDisabled}
                onClick={handleStart}
              >
                Начать запись
              </button>
              <label
                ref={uploadLabelRef}
                htmlFor="meeting-audio"
                tabIndex={-1}
                className={
                  uploadDisabled
                    ? 'record-btn record-btn-upload is-disabled'
                    : 'record-btn record-btn-upload'
                }
                aria-disabled={uploadDisabled}
                aria-describedby={
                  uploadError ? 'upload-hint upload-error' : 'upload-hint'
                }
              >
                Загрузить файл
                <input
                  id="meeting-audio"
                  className="record-file-overlay"
                  type="file"
                  accept={ACCEPT}
                  disabled={uploadDisabled}
                  onChange={(e) => void handleFileChange(e)}
                />
              </label>
            </>
          ) : uploading ? null : (
            <button
              ref={stopBtnRef}
              type="button"
              className="record-btn record-btn-stop"
              aria-disabled={stopTooSoon || !isRecording}
              onClick={() => {
                if (stopTooSoon || !isRecording) return
                void handleStop()
              }}
            >
              Стоп
            </button>
          )}
        </div>

        <p id="upload-hint" className="visually-hidden">
          Аудиофайл: m4a, caf, mp3, wav, webm и другие форматы
        </p>

        {insecure ? (
          <p className="record-error" role="alert">
            Браузер блокирует микрофон на http://. Откройте{' '}
            <a href={httpsAppUrl()}>{httpsAppUrl()}</a> и подтвердите сертификат:
            «Дополнительно» → «Перейти на сайт».
          </p>
        ) : null}

        {error ? (
          <p className="record-error" role="alert">
            {error}
          </p>
        ) : null}

        {uploadError ? (
          <p id="upload-error" className="record-error" role="alert">
            {uploadError}
          </p>
        ) : null}
      </div>
    </main>
  )
}
