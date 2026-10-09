import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, type MeetingDetail, type TranscriptTurn } from '../api'

type TranscriptView = {
  text: string
  turns: TranscriptTurn[]
  diarized: boolean
  error: string | null
}

const MARK_INTERVAL = 300

function formatClock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const secs = total % 60
  const mm = String(minutes).padStart(2, '0')
  const ss = String(secs).padStart(2, '0')
  return hours ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`
}

function SpeakerTranscript({ turns }: { turns: TranscriptTurn[] }) {
  const blocks: { time: string; turns: TranscriptTurn[] }[] = []
  let lastMark = -1
  for (const turn of turns) {
    const mark = Math.floor(turn.start / MARK_INTERVAL) * MARK_INTERVAL
    if (mark !== lastMark || blocks.length === 0) {
      blocks.push({ time: `[${formatClock(mark)}]`, turns: [] })
      lastMark = mark
    }
    blocks[blocks.length - 1].turns.push(turn)
  }
  return (
    <div className="consensus-transcript-text">
      {blocks.map((block, blockIndex) => (
        <section key={`${block.time}-${blockIndex}`} className="transcript-block">
          <h3 className="transcript-time">{block.time}</h3>
          {block.turns.map((turn, turnIndex) => (
            <article key={`${blockIndex}-${turnIndex}`} className="transcript-turn">
              <h4 className="transcript-speaker">{turn.speaker}</h4>
              <p>{turn.text}</p>
            </article>
          ))}
        </section>
      ))}
    </div>
  )
}

function TimedTranscript({ text }: { text: string }) {
  const blocks: { time: string | null; lines: string[] }[] = []
  for (const line of text.split('\n')) {
    if (/^\[\d[\d:]*\]$/.test(line)) {
      blocks.push({ time: line, lines: [] })
      continue
    }
    if (blocks.length === 0) {
      blocks.push({ time: null, lines: [line] })
    } else {
      blocks[blocks.length - 1].lines.push(line)
    }
  }
  return (
    <div className="consensus-transcript-text">
      {blocks.map((block, index) => (
        <section key={index} className="transcript-block">
          {block.time ? <h3 className="transcript-time">{block.time}</h3> : null}
          {block.lines.some((line) => line.length > 0) ? (
            <p>{block.lines.join('\n')}</p>
          ) : null}
        </section>
      ))}
    </div>
  )
}

function CopyIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h10" />
    </svg>
  )
}

function PencilIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L8 18l-4 1 1-4Z" />
    </svg>
  )
}

function MeetingTitle({
  title,
  onRename,
}: {
  title: string
  onRename: (title: string) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(title)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const cancelRef = useRef(false)

  useEffect(() => {
    if (!editing) setDraft(title)
  }, [title, editing])

  useEffect(() => {
    if (!editing) return
    inputRef.current?.focus()
    inputRef.current?.select()
  }, [editing])

  const cancel = () => {
    cancelRef.current = true
    setDraft(title)
    setError(null)
    setEditing(false)
  }

  const save = async () => {
    if (cancelRef.current) {
      cancelRef.current = false
      return
    }
    const next = draft.trim()
    if (!next || next === title) {
      setDraft(title)
      setError(null)
      setEditing(false)
      return
    }
    setBusy(true)
    setError(null)
    try {
      await onRename(next)
      setEditing(false)
    } catch {
      setError('Не удалось переименовать')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="consensus-title">
      {editing ? (
        <input
          ref={inputRef}
          className="consensus-title-input"
          value={draft}
          disabled={busy}
          maxLength={200}
          aria-label="Название встречи"
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => void save()}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              event.currentTarget.blur()
            }
            if (event.key === 'Escape') {
              event.preventDefault()
              cancel()
            }
          }}
        />
      ) : (
        <>
          <h1>{title}</h1>
          <button
            type="button"
            className="consensus-rename"
            aria-label="Переименовать встречу"
            onClick={() => setEditing(true)}
          >
            <PencilIcon />
          </button>
        </>
      )}
      {error ? (
        <p className="consensus-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 12.5 9.5 17 19 7" />
    </svg>
  )
}

/** Meeting screen: speaker transcript and a copy control. */
export function ConsensusPage() {
  const { id } = useParams<{ id: string }>()
  const meetingId = Number(id)

  const [meeting, setMeeting] = useState<MeetingDetail | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [transcript, setTranscript] = useState<TranscriptView | null>(null)
  const [transcriptLoading, setTranscriptLoading] = useState(false)
  const [transcriptError, setTranscriptError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState<string | null>(null)
  const copiedResetRef = useRef<ReturnType<typeof setTimeout> | null>(null)

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
    if (!Number.isFinite(meetingId) || meetingId <= 0) return
    setTranscriptLoading(true)
    setTranscriptError(null)
    try {
      const res = await api.getTranscript(meetingId)
      setTranscript({
        text: res.available ? res.text : '',
        turns: res.turns ?? [],
        diarized: Boolean(res.diarized),
        error: res.error,
      })
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
    void loadTranscript()
  }, [loadTranscript])

  useEffect(() => {
    return () => {
      if (copiedResetRef.current) clearTimeout(copiedResetRef.current)
    }
  }, [])

  const handleRename = async (title: string) => {
    const updated = await api.patchMeeting(meetingId, title)
    setMeeting((prev) => (prev ? { ...prev, title: updated.title } : prev))
    window.dispatchEvent(new Event('sten-meetings-changed'))
  }

  const handleCopyTranscript = async () => {
    if (!transcript?.text) return
    setCopyError(null)
    try {
      await navigator.clipboard.writeText(transcript.text)
      setCopied(true)
      if (copiedResetRef.current) clearTimeout(copiedResetRef.current)
      copiedResetRef.current = setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
      setCopyError('Не удалось скопировать')
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

  return (
    <main className="consensus-page">
      <header className="consensus-header">
        <MeetingTitle title={meeting.title} onRename={handleRename} />
        <button
          type="button"
          className="consensus-copy"
          aria-label={copied ? 'Скопировано' : 'Копировать текст записи'}
          disabled={!transcript?.text}
          onClick={() => void handleCopyTranscript()}
        >
          {copied ? <CheckIcon /> : <CopyIcon />}
        </button>
        <span className="visually-hidden" aria-live="polite">
          {copied ? 'Текст скопирован в буфер обмена' : ''}
        </span>
      </header>

      {loadError ? (
        <p className="consensus-error" role="alert">
          {loadError}
        </p>
      ) : null}

      <section className="consensus-transcript" aria-label="Полный текст записи">
        {transcriptLoading ? (
          <p className="consensus-loading">Загрузка текста…</p>
        ) : null}
        {transcriptError ? (
          <p className="consensus-error" role="alert">
            {transcriptError}
          </p>
        ) : null}
        {!transcriptLoading && !transcriptError && transcript?.text === '' ? (
          <p className="consensus-empty">Текст записи пока недоступен.</p>
        ) : null}
        {!transcriptLoading && transcript?.error ? (
          <p className="consensus-error" role="alert">
            {transcript.error}
          </p>
        ) : null}
        {copyError ? (
          <p className="consensus-error" role="alert">
            {copyError}
          </p>
        ) : null}
        {!transcriptLoading && transcript?.text ? (
          transcript.diarized && transcript.turns.length > 0 ? (
            <SpeakerTranscript turns={transcript.turns} />
          ) : (
            <TimedTranscript text={transcript.text} />
          )
        ) : null}
      </section>
    </main>
  )
}
