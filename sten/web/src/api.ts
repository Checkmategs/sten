/** Typed client for Sten meeting API. Same-origin in prod; Vite proxies /api in dev. */

// Dev: Vite `base` is `/sten/`, but the proxy only matches `/api` → use '' so
// requests hit `/api/...`. Prod (nginx strips `/sten`): use `/sten` → `/sten/api/...`.
const baseURL = import.meta.env.DEV
  ? ''
  : import.meta.env.BASE_URL.replace(/\/$/, '')

export type MeetingStatus =
  | 'recording'
  | 'processing'
  | 'ready'
  | 'consensus'
  | 'error'

export type ItemStatus = 'pending' | 'accepted'

export type ItemCounts = Record<string, number>

export interface Meeting {
  id: number
  title: string
  status: MeetingStatus
  created_at: string
  error: string | null
}

export interface Item {
  id: number
  meeting_id: number
  text: string
  category: string
  theme: string
  status: ItemStatus
  position: number
}

export interface MeetingDetail extends Meeting {
  items: Item[]
  counts: ItemCounts
}

export interface HealthResponse {
  ok: boolean
}

export interface MeetingSummary {
  id: number
  title: string
  status: MeetingStatus
  created_at: string
}

export interface CreateMeetingResponse {
  id: number
  title: string
  status: MeetingStatus
}

export interface ChunkUploadResponse {
  bytes_written: number
}

export interface StopMeetingResponse {
  id: number
  status: MeetingStatus
}

export interface MeetingStatusResponse {
  status: MeetingStatus
  error: string | null
  counts: ItemCounts
  progress: ProcessProgress | null
}

export interface ProcessProgress {
  step: number
  total: number
  percent: number
  label: string
}

export interface AudioUploadResponse {
  id: number
  status: MeetingStatus
  filename: string
  bytes: number
}

export interface TranscriptTurn {
  speaker: string
  start: number
  end: number
  text: string
}

export interface TranscriptResponse {
  text: string
  available: boolean
  turns: TranscriptTurn[]
  diarized: boolean
  busy: boolean
  error: string | null
}

export interface ReportParticipant {
  speaker: string
  role: string
  name: string
}

export interface ReportTopic {
  title: string
  text: string
}

export interface ReportDecision {
  text: string
  initiator: string
}

export interface ReportTask {
  text: string
  assignee: string
  due: string
}

export interface MeetingReport {
  available: boolean
  title: string
  summary: string
  outcome: string
  participants: ReportParticipant[]
  topics: ReportTopic[]
  decisions: ReportDecision[]
  tasks: ReportTask[]
  text: string
}

export interface SpeakerRow {
  name: string
  count: number
}

/** Meeting screen payload: transcript and brief arrive together. */
export interface MeetingMaterials {
  meeting: MeetingDetail
  transcript: TranscriptResponse
  report: MeetingReport
  speakers: SpeakerRow[]
  speakerError: string | null
}

export type ExportFormat = 'txt' | 'srt' | 'docx'

export interface PatchItemBody {
  text?: string
  status?: ItemStatus
}

export interface RewriteBody {
  objection: string
}

export interface AuthUser {
  id: number
  name: string
}

export function apiDetail(raw: string): string {
  const start = raw.indexOf('{')
  if (start >= 0) {
    try {
      const parsed = JSON.parse(raw.slice(start)) as { detail?: unknown }
      if (typeof parsed.detail === 'string') return parsed.detail
    } catch {
      /* keep the raw body */
    }
  }
  return raw.trim()
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${baseURL}${path}`, { ...init, credentials: 'include' })
  if (res.status === 401 && !path.startsWith('/api/auth/')) {
    window.dispatchEvent(new Event('sten-unauthorized'))
  }
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`API ${res.status} ${path}${detail ? `: ${detail}` : ''}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  health(): Promise<HealthResponse> {
    return request('/api/health')
  },

  me(): Promise<AuthUser> {
    return request('/api/auth/me')
  },

  register(name: string, password: string): Promise<AuthUser> {
    return request('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, password }),
    })
  },

  login(name: string, password: string): Promise<AuthUser> {
    return request('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, password }),
    })
  },

  logout(): Promise<{ ok: boolean }> {
    return request('/api/auth/logout', { method: 'POST' })
  },

  listMeetings(includeId?: number): Promise<MeetingSummary[]> {
    const query =
      includeId != null ? `?include_id=${encodeURIComponent(String(includeId))}` : ''
    return request(`/api/meetings${query}`)
  },

  createMeeting(title: string): Promise<CreateMeetingResponse> {
    return request('/api/meetings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    })
  },

  getMeeting(id: number): Promise<MeetingDetail> {
    return request(`/api/meetings/${id}`)
  },

  deleteMeeting(id: number): Promise<{ ok: boolean; id: number }> {
    return request(`/api/meetings/${id}`, { method: 'DELETE' })
  },

  patchMeeting(id: number, title: string): Promise<CreateMeetingResponse> {
    return request(`/api/meetings/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    })
  },

  getTranscript(id: number): Promise<TranscriptResponse> {
    return request(`/api/meetings/${id}/transcript`)
  },

  getReport(id: number): Promise<MeetingReport> {
    return request(`/api/meetings/${id}/report`)
  },

  meetingAudioUrl(id: number): string {
    return `${baseURL}/api/meetings/${id}/audio`
  },

  speakerSampleUrl(id: number, name: string): string {
    return `${baseURL}/api/meetings/${id}/speakers/sample?name=${encodeURIComponent(name)}`
  },

  getSpeakers(id: number): Promise<{ speakers: SpeakerRow[] }> {
    return request(`/api/meetings/${id}/speakers`)
  },

  /** Meeting, transcript, and brief in one round so the screen can open complete. */
  async loadMeetingMaterials(id: number): Promise<MeetingMaterials> {
    const [meeting, transcript, report, speakers] = await Promise.all([
      this.getMeeting(id),
      this.getTranscript(id),
      this.getReport(id),
      this.getSpeakers(id).then(
        (res) => ({ speakers: res.speakers, speakerError: null as string | null }),
        (err: unknown) => ({
          speakers: [] as SpeakerRow[],
          speakerError: err instanceof Error ? err.message : String(err),
        }),
      ),
    ])
    return {
      meeting,
      transcript,
      report,
      speakers: speakers.speakers,
      speakerError: speakers.speakerError,
    }
  },

  renameSpeaker(
    id: number,
    source: string,
    target: string,
  ): Promise<{ speakers: SpeakerRow[]; report: MeetingReport }> {
    return request(`/api/meetings/${id}/speakers/rename`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, target }),
    })
  },

  deleteSpeaker(id: number, name: string): Promise<{ speakers: SpeakerRow[] }> {
    return request(`/api/meetings/${id}/speakers/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
  },

  async downloadExport(id: number, format: ExportFormat): Promise<void> {
    const res = await fetch(
      `${baseURL}/api/meetings/${id}/export?format=${format}`,
      { credentials: 'include' },
    )
    if (res.status === 401) {
      window.dispatchEvent(new Event('sten-unauthorized'))
    }
    if (!res.ok) {
      const detail = await res.text().catch(() => '')
      throw new Error(apiDetail(detail) || `API ${res.status}`)
    }
    const blob = await res.blob()
    const header = res.headers.get('Content-Disposition') || ''
    const match = /filename\*=UTF-8''([^;]+)/.exec(header)
    const filename = match ? decodeURIComponent(match[1]) : `meeting.${format}`
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.click()
    URL.revokeObjectURL(url)
  },

  diarize(id: number): Promise<{ id: number; status: string }> {
    return request(`/api/meetings/${id}/diarize`, { method: 'POST' })
  },

  uploadChunk(id: number, data: Blob | ArrayBuffer): Promise<ChunkUploadResponse> {
    return request(`/api/meetings/${id}/chunks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: data,
    })
  },

  uploadMeetingAudio(
    id: number,
    file: File,
    onProgress: (ratio: number) => void,
  ): Promise<AudioUploadResponse> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', `${baseURL}/api/meetings/${id}/audio`)
      xhr.withCredentials = true
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && event.total > 0) {
          onProgress(event.loaded / event.total)
        }
      }
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText) as AudioUploadResponse)
          } catch {
            reject(new Error(`API ${xhr.status} /api/meetings/${id}/audio: invalid JSON`))
          }
          return
        }
        const detail = xhr.responseText?.trim()
        reject(
          new Error(
            `API ${xhr.status} /api/meetings/${id}/audio${detail ? `: ${detail}` : ''}`,
          ),
        )
      }
      xhr.onerror = () => {
        reject(new Error(`API network error /api/meetings/${id}/audio`))
      }
      xhr.onabort = () => {
        reject(new Error('Загрузка файла отменена'))
      }
      const form = new FormData()
      form.append('file', file)
      xhr.send(form)
    })
  },

  stopMeeting(id: number): Promise<StopMeetingResponse> {
    return request(`/api/meetings/${id}/stop`, { method: 'POST' })
  },

  getStatus(id: number): Promise<MeetingStatusResponse> {
    return request(`/api/meetings/${id}/status`)
  },

  patchItem(meetingId: number, itemId: number, body: PatchItemBody): Promise<Item> {
    return request(`/api/meetings/${meetingId}/items/${itemId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  },

  rewriteItem(meetingId: number, itemId: number, body: RewriteBody): Promise<Item> {
    return request(`/api/meetings/${meetingId}/items/${itemId}/rewrite`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  },

  elaborateItem(meetingId: number, itemId: number): Promise<Item> {
    return request(`/api/meetings/${meetingId}/items/${itemId}/elaborate`, {
      method: 'POST',
    })
  },

  resummarize(id: number): Promise<StopMeetingResponse> {
    return request(`/api/meetings/${id}/resummarize`, { method: 'POST' })
  },
}
