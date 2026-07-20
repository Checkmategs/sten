/** Typed client for Sten meeting API. Same-origin in prod; Vite proxies /api in dev. */

const baseURL = ''

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

  uploadChunk(id: number, data: Blob | ArrayBuffer): Promise<ChunkUploadResponse> {
    return request(`/api/meetings/${id}/chunks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: data,
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
