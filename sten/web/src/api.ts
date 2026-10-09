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

export interface PatchItemBody {
  text?: string
  status?: ItemStatus
}

export interface RewriteBody {
  objection: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${baseURL}${path}`, init)
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
