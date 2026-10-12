import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  api,
  apiDetail,
  type ExportFormat,
  type DialogueMap,
  type MeetingDetail,
  type MeetingMaterials,
  type MeetingReport,
  type SpeakerRow,
  type TranscriptResponse,
  type TranscriptTurn,
} from '../api'
import { DialogueMapView } from './DialogueMap'

type TranscriptView = {
  text: string
  turns: TranscriptTurn[]
  diarized: boolean
  error: string | null
}

type MeetingTab = 'transcript' | 'report' | 'speakers' | 'dialogue'

function transcriptView(res: TranscriptResponse): TranscriptView {
  return {
    text: res.available ? res.text : '',
    turns: res.turns ?? [],
    diarized: Boolean(res.diarized),
    error: res.error,
  }
}

function materialsFor(state: unknown, meetingId: number): MeetingMaterials | null {
  if (!state || typeof state !== 'object' || !('materials' in state)) return null
  const materials = (state as { materials?: MeetingMaterials }).materials
  if (!materials || materials.meeting.id !== meetingId) return null
  return materials
}

function formatClock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const secs = total % 60
  const mm = String(minutes).padStart(2, '0')
  const ss = String(secs).padStart(2, '0')
  return hours ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`
}

function TurnList({
  turns,
  diarized,
  onSeek,
}: {
  turns: TranscriptTurn[]
  diarized: boolean
  onSeek: (seconds: number) => void
}) {
  return (
    <div className="consensus-transcript-text">
      {turns.map((turn, index) => (
        <article key={`${turn.start}-${index}`} className="transcript-turn">
          <div className="transcript-turn-head">
            <button
              type="button"
              className="transcript-seek"
              onClick={() => onSeek(turn.start)}
            >
              {formatClock(turn.start)}
            </button>
            {diarized ? <h4 className="transcript-speaker">{turn.speaker}</h4> : null}
          </div>
          <p>{turn.text}</p>
        </article>
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

function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 4v10" />
      <path d="m7 11 5 5 5-5" />
      <path d="M5 19h14" />
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

function PlayIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M8.5 6.2v11.6L18 12 8.5 6.2z" />
    </svg>
  )
}

function PauseIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 6h3.2v12H7zM13.8 6H17v12h-3.2z" />
    </svg>
  )
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 12.5 9.5 17 19 7" />
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

function ReportView({ report }: { report: MeetingReport }) {
  const hasBody =
    report.title ||
    report.summary ||
    report.outcome ||
    report.participants.length > 0 ||
    report.topics.length > 0 ||
    report.decisions.length > 0 ||
    report.tasks.length > 0
  if (!report.available || !hasBody) {
    return <p className="consensus-empty">Краткий обзор появится после обработки записи.</p>
  }
  return (
    <div className="meeting-report">
      {report.title ? (
        <section className="consensus-section">
          <h2>Название встречи</h2>
          <p>{report.title}</p>
        </section>
      ) : null}
      {report.participants.some((person) => person.speaker) ? (
        <section className="consensus-section">
          <h2>Участники</h2>
          <ul className="report-list">
            {report.participants.map((person, index) =>
              person.speaker ? (
                <li key={`${person.speaker}-${index}`}>{person.speaker}</li>
              ) : null,
            )}
          </ul>
        </section>
      ) : null}
      {report.summary ? (
        <section className="consensus-section">
          <h2>Краткое резюме</h2>
          <p>{report.summary}</p>
        </section>
      ) : null}
      {report.topics.length > 0 ? (
        <section className="consensus-section">
          <h2>Ключевые темы</h2>
          <ul className="report-list">
            {report.topics.map((topic, index) => (
              <li key={`${topic.title}-${index}`}>
                {topic.title && topic.text ? (
                  <>
                    <strong>{topic.title}</strong>
                    {' — '}
                    {topic.text}
                  </>
                ) : (
                  topic.title || topic.text
                )}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {report.decisions.length > 0 ? (
        <section className="consensus-section">
          <h2>Принятые решения</h2>
          <ul className="report-list">
            {report.decisions.map((decision, index) => (
              <li key={`${decision.text}-${index}`}>
                {decision.text}
                {decision.initiator ? ` — инициатор: ${decision.initiator}` : ''}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {report.tasks.length > 0 ? (
        <section className="consensus-section">
          <h2>Задачи и договорённости</h2>
          <ul className="report-list">
            {report.tasks.map((task, index) => (
              <li key={`${task.text}-${index}`}>
                {task.text}
                {task.assignee ? ` — ответственный: ${task.assignee}` : ''}
                {task.due ? ` — срок: ${task.due}` : ''}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {report.outcome ? (
        <section className="consensus-section">
          <h2>Итог встречи</h2>
          <p>{report.outcome}</p>
        </section>
      ) : null}
    </div>
  )
}

function playWasInterrupted(err: unknown): boolean {
  return (
    err instanceof DOMException &&
    (err.name === 'AbortError' || err.name === 'NotAllowedError')
  )
}

function SpeakerClip({ name, src }: { name: string; src: string }) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [playing, setPlaying] = useState(false)
  const [failed, setFailed] = useState(false)

  const toggle = () => {
    const audio = audioRef.current
    if (!audio) return
    if (!audio.paused && !audio.ended) {
      audio.pause()
      return
    }
    document.querySelectorAll('audio.speaker-clip').forEach((node) => {
      if (node !== audio) (node as HTMLAudioElement).pause()
    })
    if (audio.ended) audio.currentTime = 0
    void audio.play().catch((err: unknown) => {
      if (playWasInterrupted(err)) return
      setFailed(true)
    })
  }

  if (failed) {
    return <span className="speaker-sample-missing">Фрагмент недоступен</span>
  }

  return (
    <div className="speaker-sample">
      <button
        type="button"
        className="speaker-play"
        aria-label={playing ? `Пауза, ${name}` : `Прослушать фрагмент голоса, ${name}`}
        onClick={toggle}
      >
        {playing ? <PauseIcon /> : <PlayIcon />}
      </button>
      <audio
        ref={audioRef}
        className="speaker-clip"
        preload="none"
        src={src}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onError={() => {
          if (audioRef.current?.error?.code === MediaError.MEDIA_ERR_ABORTED) return
          setFailed(true)
        }}
      />
    </div>
  )
}

function SpeakersPanel({
  meetingId,
  speakers,
  busy,
  error,
  onRename,
  onMerge,
}: {
  meetingId: number
  speakers: SpeakerRow[]
  busy: boolean
  error: string | null
  onRename: (source: string, target: string) => Promise<void>
  onMerge: (source: string, target: string) => Promise<void>
}) {
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [merging, setMerging] = useState<string | null>(null)
  const mergeRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!merging) return
    const close = (event: MouseEvent) => {
      if (!mergeRef.current?.contains(event.target as Node)) setMerging(null)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMerging(null)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', onKey)
    }
  }, [merging])

  const startEdit = (name: string) => {
    setMerging(null)
    setEditing(name)
    setDraft(name)
  }

  const save = async (source: string) => {
    const next = draft.trim()
    if (!next || next === source) {
      setEditing(null)
      return
    }
    try {
      await onRename(source, next)
      setEditing(null)
    } catch {
      /* The panel shows the error and keeps the draft. */
    }
  }

  if (speakers.length === 0 && !error) {
    return <p className="consensus-empty">Спикеры появятся после разметки записи.</p>
  }

  return (
    <div className="speakers-panel">
      <ul className="speaker-list">
        {speakers.map((speaker) => (
          <li key={speaker.name} className="speaker-row">
            <div className="speaker-main">
              {speaker.count > 0 ? (
                <SpeakerClip
                  name={speaker.name}
                  src={api.speakerSampleUrl(meetingId, speaker.name)}
                />
              ) : null}
              {editing === speaker.name ? (
                <input
                  className="speaker-input"
                  value={draft}
                  maxLength={80}
                  aria-label={`Имя спикера ${speaker.name}`}
                  disabled={busy}
                  autoFocus
                  onChange={(event) => setDraft(event.target.value)}
                  onBlur={() => void save(speaker.name)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault()
                      event.currentTarget.blur()
                    }
                    if (event.key === 'Escape') {
                      event.preventDefault()
                      setEditing(null)
                    }
                  }}
                />
              ) : (
                <span className="speaker-name">
                  {speaker.name}
                  <span className="speaker-count">{speaker.count}</span>
                </span>
              )}
            </div>
            <button
              type="button"
              className="speaker-action"
              aria-label={`Переименовать ${speaker.name}`}
              disabled={busy}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => startEdit(speaker.name)}
            >
              Переименовать
            </button>
            <div
              className="speaker-merge"
              ref={merging === speaker.name ? mergeRef : undefined}
            >
              <button
                type="button"
                className="speaker-action"
                aria-label={`Объединить ${speaker.name}`}
                aria-expanded={merging === speaker.name}
                aria-haspopup="menu"
                disabled={busy || speakers.length < 2}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  setEditing(null)
                  setMerging((current) => (current === speaker.name ? null : speaker.name))
                }}
              >
                Объединить
              </button>
              {merging === speaker.name ? (
                <div
                  className="speaker-merge-list"
                  role="menu"
                  aria-label={`С кем объединить ${speaker.name}`}
                >
                  <p className="speaker-merge-hint">Объединить с</p>
                  {speakers
                    .filter((other) => other.name !== speaker.name)
                    .map((other) => (
                      <button
                        key={other.name}
                        type="button"
                        role="menuitem"
                        disabled={busy}
                        onClick={() => {
                          void onMerge(speaker.name, other.name)
                            .then(() => setMerging(null))
                            .catch(() => {})
                        }}
                      >
                        {other.name}
                      </button>
                    ))}
                </div>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
      {error ? (
        <p className="consensus-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}

/** Meeting screen: transcript, brief, playback, speakers, and export. */
export function ConsensusPage() {
  const { id } = useParams<{ id: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const meetingId = Number(id)
  const seeded = materialsFor(location.state, meetingId)

  const [meeting, setMeeting] = useState<MeetingDetail | null>(seeded?.meeting ?? null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [transcript, setTranscript] = useState<TranscriptView | null>(
    seeded ? transcriptView(seeded.transcript) : null,
  )
  const [transcriptLoading, setTranscriptLoading] = useState(false)
  const [transcriptError, setTranscriptError] = useState<string | null>(null)
  const [report, setReport] = useState<MeetingReport | null>(seeded?.report ?? null)
  const [dialogue, setDialogue] = useState<DialogueMap | null>(null)
  const [dialogueNote, setDialogueNote] = useState<string | null>(null)
  const [dialoguePoll, setDialoguePoll] = useState(0)
  const [speakers, setSpeakers] = useState<SpeakerRow[]>(seeded?.speakers ?? [])
  const [speakerBusy, setSpeakerBusy] = useState(false)
  const [speakerError, setSpeakerError] = useState<string | null>(
    seeded?.speakerError ? apiDetail(seeded.speakerError) : null,
  )
  const [viewReady, setViewReady] = useState(seeded != null)
  const [tab, setTab] = useState<MeetingTab>('transcript')
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState<string | null>(null)
  const [exportOpen, setExportOpen] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  const [audioFailed, setAudioFailed] = useState(false)
  const copiedResetRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const exportRef = useRef<HTMLDivElement>(null)

  const loadTranscript = useCallback(async () => {
    if (!Number.isFinite(meetingId) || meetingId <= 0) return
    setTranscriptLoading(true)
    setTranscriptError(null)
    try {
      setTranscript(transcriptView(await api.getTranscript(meetingId)))
    } catch (err) {
      setTranscriptError(err instanceof Error ? err.message : String(err))
    } finally {
      setTranscriptLoading(false)
    }
  }, [meetingId])

  useEffect(() => {
    if (!Number.isFinite(meetingId) || meetingId <= 0) {
      setMeeting(null)
      setLoadError('Некорректный идентификатор встречи')
      setViewReady(true)
      return
    }
    const apply = (materials: MeetingMaterials) => {
      setMeeting(materials.meeting)
      setTranscript(transcriptView(materials.transcript))
      setReport(materials.report)
      setSpeakers(materials.speakers)
      setSpeakerError(materials.speakerError ? apiDetail(materials.speakerError) : null)
      setLoadError(null)
      setTranscriptError(null)
    }

    const ready = materialsFor(location.state, meetingId)
    if (ready) {
      apply(ready)
      setViewReady(true)
      return
    }

    let cancelled = false
    setViewReady(false)
    setLoadError(null)
    setTranscriptError(null)
    void (async () => {
      try {
        const materials = await api.loadMeetingMaterials(meetingId)
        if (cancelled) return
        apply(materials)
      } catch (err) {
        if (cancelled) return
        setMeeting(null)
        setLoadError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setViewReady(true)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [meetingId, location.state])

  useEffect(() => {
    if (meeting?.status !== 'processing') return
    navigate(`/m/${meetingId}/process`, { replace: true })
  }, [meeting?.status, meetingId, navigate])

  useEffect(() => {
    if (tab !== 'dialogue' || !Number.isFinite(meetingId) || meetingId <= 0) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    const load = async () => {
      try {
        const map = await api.getDialogue(meetingId)
        if (cancelled) return
        setDialogue(map)
        setDialogueNote(null)
        if (map.busy) timer = setTimeout(() => void load(), 2000)
      } catch (err) {
        if (cancelled) return
        setDialogueNote(apiDetail(err instanceof Error ? err.message : String(err)))
      }
    }

    void load()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [tab, meetingId, dialoguePoll])

  useEffect(() => {
    return () => {
      if (copiedResetRef.current) clearTimeout(copiedResetRef.current)
    }
  }, [])

  useEffect(() => {
    if (!exportOpen) return
    const close = (event: MouseEvent) => {
      if (!exportRef.current?.contains(event.target as Node)) setExportOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [exportOpen])

  const handleRename = async (title: string) => {
    const updated = await api.patchMeeting(meetingId, title)
    setMeeting((prev) => (prev ? { ...prev, title: updated.title } : prev))
    window.dispatchEvent(new Event('sten-meetings-changed'))
  }

  const copyText =
    tab === 'report'
      ? report?.text || ''
      : tab === 'transcript'
        ? transcript?.text || ''
        : tab === 'dialogue'
          ? dialogue?.text || ''
          : ''

  const handleBuildDialogue = async () => {
    setDialogueNote(null)
    setDialogue((current) =>
      current
        ? { ...current, busy: true, error: null }
        : { available: false, busy: true, error: null, questions: [], text: '' },
    )
    try {
      setDialogue(await api.buildDialogue(meetingId))
      setDialoguePoll((value) => value + 1)
    } catch (err) {
      setDialogue((current) => (current ? { ...current, busy: false } : current))
      setDialogueNote(apiDetail(err instanceof Error ? err.message : String(err)))
    }
  }

  const handleCopy = async () => {
    if (!copyText) return
    setCopyError(null)
    try {
      await navigator.clipboard.writeText(copyText)
      setCopied(true)
      if (copiedResetRef.current) clearTimeout(copiedResetRef.current)
      copiedResetRef.current = setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
      setCopyError('Не удалось скопировать')
    }
  }

  const seek = (seconds: number) => {
    const audio = audioRef.current
    if (!audio || audioFailed) return
    audio.currentTime = seconds
    void audio.play().catch(() => {})
  }

  const handleRenameSpeaker = async (source: string, target: string) => {
    setSpeakerBusy(true)
    setSpeakerError(null)
    try {
      const res = await api.renameSpeaker(meetingId, source, target)
      setSpeakers(res.speakers)
      setReport(res.report)
      await loadTranscript()
    } catch (err) {
      const message = apiDetail(err instanceof Error ? err.message : String(err))
      setSpeakerError(message)
      throw err
    } finally {
      setSpeakerBusy(false)
    }
  }

  const handleMergeSpeaker = async (source: string, target: string) => {
    setSpeakerBusy(true)
    setSpeakerError(null)
    try {
      const res = await api.mergeSpeakers(meetingId, source, target)
      setSpeakers(res.speakers)
      setReport(res.report)
      await loadTranscript()
    } catch (err) {
      const message = apiDetail(err instanceof Error ? err.message : String(err))
      setSpeakerError(message)
      throw err
    } finally {
      setSpeakerBusy(false)
    }
  }

  const handleExport = async (format: ExportFormat) => {
    setExportOpen(false)
    setExportError(null)
    try {
      await api.downloadExport(meetingId, format)
    } catch (err) {
      setExportError(apiDetail(err instanceof Error ? err.message : String(err)))
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

  if (!viewReady || !meeting || meeting.id !== meetingId || meeting.status === 'processing') {
    return (
      <main className="consensus-page">
        <p className="consensus-loading">Загрузка…</p>
      </main>
    )
  }

  const copyLabel =
    tab === 'report'
      ? copied
        ? 'Скопировано'
        : 'Копировать обзор'
      : tab === 'transcript'
        ? copied
          ? 'Скопировано'
          : 'Копировать текст записи'
        : tab === 'dialogue'
          ? copied
            ? 'Скопировано'
            : 'Копировать карту'
          : 'Копировать'

  return (
    <main className="consensus-page">
      <header className="consensus-header">
        <MeetingTitle title={meeting.title} onRename={handleRename} />
        <div className="consensus-actions">
          <button
            type="button"
            className="consensus-copy"
            aria-label={copyLabel}
            disabled={!copyText}
            onClick={() => void handleCopy()}
          >
            {copied ? <CheckIcon /> : <CopyIcon />}
          </button>
          <div className="export-menu" ref={exportRef}>
            <button
              type="button"
              className="consensus-copy"
              aria-label="Скачать"
              aria-haspopup="menu"
              aria-expanded={exportOpen}
              onClick={() => setExportOpen((open) => !open)}
            >
              <DownloadIcon />
            </button>
            {exportOpen ? (
              <div className="export-menu-list" role="menu">
                <button type="button" role="menuitem" onClick={() => void handleExport('txt')}>
                  Текст TXT
                </button>
                <button type="button" role="menuitem" onClick={() => void handleExport('srt')}>
                  Субтитры SRT
                </button>
                <button type="button" role="menuitem" onClick={() => void handleExport('docx')}>
                  Обзор DOCX
                </button>
              </div>
            ) : null}
          </div>
        </div>
        <span className="visually-hidden" aria-live="polite">
          {copied ? 'Текст скопирован в буфер обмена' : ''}
        </span>
      </header>

      {loadError ? (
        <p className="consensus-error" role="alert">
          {loadError}
        </p>
      ) : null}
      {copyError ? (
        <p className="consensus-error" role="alert">
          {copyError}
        </p>
      ) : null}
      {exportError ? (
        <p className="consensus-error" role="alert">
          {exportError}
        </p>
      ) : null}

      <div className="meeting-tabs" role="tablist" aria-label="Материалы встречи">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'speakers'}
          className="meeting-tab"
          onClick={() => setTab('speakers')}
        >
          Спикеры
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'transcript'}
          className="meeting-tab"
          onClick={() => setTab('transcript')}
        >
          Расшифровка
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'report'}
          className="meeting-tab"
          onClick={() => setTab('report')}
        >
          Краткий обзор
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'dialogue'}
          className="meeting-tab"
          onClick={() => setTab('dialogue')}
        >
          Карта диалога
        </button>
      </div>

      {tab === 'transcript' ? (
        <section className="consensus-transcript" role="tabpanel" aria-label="Полный текст записи">
          {transcriptLoading ? <p className="consensus-loading">Загрузка текста…</p> : null}
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
          {!transcriptLoading && transcript?.text ? (
            transcript.turns.length > 0 ? (
              <TurnList
                turns={transcript.turns}
                diarized={transcript.diarized}
                onSeek={seek}
              />
            ) : (
              <TimedTranscript text={transcript.text} />
            )
          ) : null}
          {audioFailed ? (
            <p className="consensus-empty">Аудио недоступно.</p>
          ) : (
            <audio
              ref={audioRef}
              className="transcript-player"
              controls
              preload="metadata"
              src={api.meetingAudioUrl(meetingId)}
              onError={() => setAudioFailed(true)}
            />
          )}
        </section>
      ) : tab === 'report' ? (
        <section role="tabpanel" aria-label="Краткий обзор совещания">
          {report ? (
            <ReportView report={report} />
          ) : (
            <p className="consensus-empty">Краткий обзор появится после обработки записи.</p>
          )}
        </section>
      ) : tab === 'dialogue' ? (
        <section role="tabpanel" aria-label="Карта диалога">
          {dialogueNote ? (
            <p className="consensus-error" role="alert">
              {dialogueNote}
            </p>
          ) : null}
          <DialogueMapView dialogue={dialogue} onBuild={() => void handleBuildDialogue()} />
        </section>
      ) : (
        <section role="tabpanel" aria-label="Спикеры">
          <SpeakersPanel
            meetingId={meetingId}
            speakers={speakers}
            busy={speakerBusy}
            error={speakerError}
            onRename={handleRenameSpeaker}
            onMerge={handleMergeSpeaker}
          />
        </section>
      )}
    </main>
  )
}
