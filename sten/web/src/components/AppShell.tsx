import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useEffect, useId, useState, type MouseEvent, type ReactNode } from 'react'
import { api, type MeetingStatus, type MeetingSummary } from '../api'
import { WaveCanvas } from './WaveCanvas'

interface AppShellProps {
  children: ReactNode
}

function meetingPath(status: MeetingStatus, id: number): string {
  if (status === 'ready' || status === 'consensus') return `/m/${id}/consensus`
  return `/m/${id}/process`
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 7h16" />
      <path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
      <path d="M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13" />
    </svg>
  )
}

function whenLabel(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const day = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const diff = Math.round((start.getTime() - day.getTime()) / 86_400_000)
  const hm = date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  if (diff === 0) return `Сегодня, ${hm}`
  if (diff === 1) return `Вчера, ${hm}`
  return date.toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Nina-like shell: wave, glass burger, meeting history. */
export function AppShell({ children }: AppShellProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const menuId = useId()
  const [open, setOpen] = useState(false)
  const [meetings, setMeetings] = useState<MeetingSummary[]>([])
  const [listError, setListError] = useState(false)
  const [confirmId, setConfirmId] = useState<number | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const activeMatch = location.pathname.match(/^\/m\/(\d+)/)
  const activeId = activeMatch ? Number(activeMatch[1]) : undefined

  useEffect(() => {
    let cancelled = false
    const load = () => {
      api
        .listMeetings(activeId)
        .then((rows) => {
          if (cancelled) return
          setMeetings(rows)
          setListError(false)
        })
        .catch(() => {
          if (cancelled) return
          setListError(true)
        })
    }
    load()
    window.addEventListener('sten-meetings-changed', load)
    return () => {
      cancelled = true
      window.removeEventListener('sten-meetings-changed', load)
    }
  }, [location.pathname, activeId])

  useEffect(() => {
    if (open) return
    setConfirmId(null)
    setDeleteError(null)
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    const onPointer = (event: PointerEvent) => {
      const target = event.target
      if (!(target instanceof Node)) return
      const burger = document.getElementById('sten-burger')
      const menu = document.getElementById(menuId)
      if (burger?.contains(target) || menu?.contains(target)) return
      setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onPointer)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onPointer)
    }
  }, [open, menuId])

  const removeMeeting = async (id: number) => {
    setDeleting(true)
    setDeleteError(null)
    try {
      await api.deleteMeeting(id)
      setMeetings((rows) => rows.filter((row) => row.id !== id))
      setConfirmId(null)
      if (activeId === id) {
        setOpen(false)
        navigate('/', { replace: true })
      }
    } catch {
      setDeleteError('Не удалось удалить')
    } finally {
      setDeleting(false)
    }
  }

  const startNewMeeting = (event: MouseEvent<HTMLAnchorElement>) => {
    setOpen(false)
    if (location.pathname !== '/') return
    event.preventDefault()
    navigate('/', { replace: true, state: { newMeeting: Date.now() } })
  }

  return (
    <div className="app-shell">
      <a className="app-skip" href="#sten-main">
        К содержимому
      </a>
      <WaveCanvas />

      <button
        type="button"
        id="sten-burger"
        className="burger"
        aria-label="Меню"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((value) => !value)}
      >
        <span />
        <span />
        <span />
      </button>

      <nav
        id={menuId}
        className="nav-menu"
        aria-label="История встреч"
        hidden={!open}
      >
        <Link
          to="/"
          className="nav-menu-new"
          state={{ newMeeting: Date.now() }}
          onClick={startNewMeeting}
        >
          Новая встреча
        </Link>
        <p className="nav-menu-label">История встреч</p>
        {listError ? (
          <p className="hist-empty">Не удалось загрузить встречи</p>
        ) : meetings.length === 0 ? (
          <p className="hist-empty">Пока нет записей</p>
        ) : (
          <>
          <ul className="hist-list">
            {meetings.map((meeting) => (
              <li key={meeting.id}>
                <div className="hist-row">
                  <Link
                    to={meetingPath(meeting.status, meeting.id)}
                    className={
                      meeting.id === activeId ? 'hist-item is-current' : 'hist-item'
                    }
                    onClick={() => setOpen(false)}
                  >
                    <span className="hist-title">{meeting.title}</span>
                    <span className="hist-when">{whenLabel(meeting.created_at)}</span>
                  </Link>
                  <button
                    type="button"
                    className="hist-delete"
                    aria-label={`Удалить «${meeting.title}»`}
                    aria-expanded={confirmId === meeting.id}
                    onClick={() => {
                      setDeleteError(null)
                      setConfirmId((current) =>
                        current === meeting.id ? null : meeting.id,
                      )
                    }}
                  >
                    <TrashIcon />
                  </button>
                </div>
                {confirmId === meeting.id ? (
                  <div className="hist-confirm">
                    <span>Удалить запись?</span>
                    <button
                      type="button"
                      disabled={deleting}
                      onClick={() => void removeMeeting(meeting.id)}
                    >
                      Удалить
                    </button>
                    <button
                      type="button"
                      disabled={deleting}
                      onClick={() => setConfirmId(null)}
                    >
                      Отмена
                    </button>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
          {deleteError ? (
            <p className="hist-empty" role="alert">
              {deleteError}
            </p>
          ) : null}
          </>
        )}
      </nav>

      <div className="app-main" id="sten-main">
        {children}
      </div>
    </div>
  )
}
