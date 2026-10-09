import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { api, type AuthUser } from './api'
import { AppShell } from './components/AppShell'
import { ConsensusPage } from './pages/ConsensusPage'
import { LoginPage } from './pages/LoginPage'
import { ProcessPage } from './pages/ProcessPage'
import { RecordPage } from './pages/RecordPage'

type NewMeetingState = { newMeeting?: number }

function AppRoutes() {
  const location = useLocation()
  const state = location.state as NewMeetingState | null
  const recordKey =
    location.pathname === '/' && state?.newMeeting != null
      ? String(state.newMeeting)
      : 'home'

  return (
    <Routes>
      <Route path="/" element={<RecordPage key={recordKey} />} />
      <Route path="/m/:id/process" element={<ProcessPage />} />
      <Route path="/m/:id/consensus" element={<ConsensusPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  const [user, setUser] = useState<AuthUser | null | undefined>(undefined)

  useEffect(() => {
    let cancelled = false
    api
      .me()
      .then((current) => {
        if (!cancelled) setUser(current)
      })
      .catch(() => {
        if (!cancelled) setUser(null)
      })
    const onUnauthorized = () => setUser(null)
    window.addEventListener('sten-unauthorized', onUnauthorized)
    return () => {
      cancelled = true
      window.removeEventListener('sten-unauthorized', onUnauthorized)
    }
  }, [])

  if (user === undefined) {
    return (
      <div className="app-shell">
        <p className="login-lead">Загрузка…</p>
      </div>
    )
  }

  if (user === null) {
    return <LoginPage onLogin={setUser} />
  }

  return (
    <BrowserRouter basename="/sten">
      <AppShell
        userName={user.name}
        onLogout={() => {
          void api.logout().finally(() => setUser(null))
        }}
      >
        <AppRoutes />
      </AppShell>
    </BrowserRouter>
  )
}
