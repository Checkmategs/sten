import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ConsensusPage } from './pages/ConsensusPage'
import { ProcessPage } from './pages/ProcessPage'
import { RecordPage } from './pages/RecordPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<RecordPage />} />
        <Route path="/m/:id/process" element={<ProcessPage />} />
        <Route path="/m/:id/consensus" element={<ConsensusPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
