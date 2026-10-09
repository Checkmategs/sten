import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { ConsensusPage } from './pages/ConsensusPage'
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
  return (
    <BrowserRouter basename="/sten">
      <AppShell>
        <AppRoutes />
      </AppShell>
    </BrowserRouter>
  )
}
