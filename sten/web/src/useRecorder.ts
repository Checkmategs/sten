import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'

export type RecorderPhase = 'idle' | 'starting' | 'recording' | 'stopping'

const TIMESLICE_MS = 2000
/** Software boost for quiet mics (1 = no boost). */
const MIC_GAIN = 5
const WAVE_BARS = 72
const WAVE_PUSH_MS = 42

const MIC_CONSTRAINTS: MediaStreamConstraints = {
  audio: {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
    channelCount: 1,
  },
}

export function defaultMeetingTitle(now = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `Встреча ${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`
}

export function formatElapsed(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000))
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export function httpsAppUrl(): string {
  if (typeof window === 'undefined') return 'https://10.91.0.55/sten/'
  const host = window.location.hostname || '10.91.0.55'
  return `https://${host}/sten/`
}

export function micErrorMessage(err: unknown): string {
  if (typeof window !== 'undefined' && !window.isSecureContext) {
    return (
      `Браузер блокирует микрофон на http://. Откройте ${httpsAppUrl()} ` +
      'и подтвердите сертификат: «Дополнительно» → «Перейти на сайт».'
    )
  }
  if (typeof navigator !== 'undefined' && !navigator.mediaDevices?.getUserMedia) {
    return (
      `Браузер блокирует микрофон на незащищённом адресе. Откройте ${httpsAppUrl()} ` +
      'и подтвердите сертификат: «Дополнительно» → «Перейти на сайт».'
    )
  }
  if (err instanceof DOMException) {
    if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
      return 'Нет доступа к микрофону. Разрешите использование микрофона в настройках браузера.'
    }
    if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
      return 'Микрофон не найден. Подключите микрофон и попробуйте снова.'
    }
    if (err.name === 'NotReadableError' || err.name === 'TrackStartError') {
      return 'Микрофон занят другим приложением. Закройте его и попробуйте снова.'
    }
  }
  if (err instanceof Error && err.message) {
    if (err.message.includes('getUserMedia') || err.message.includes('mediaDevices')) {
      return (
        `Браузер блокирует микрофон на незащищённом адресе. Откройте ${httpsAppUrl()} ` +
        'и подтвердите сертификат: «Дополнительно» → «Перейти на сайт».'
      )
    }
    return `Не удалось получить доступ к микрофону: ${err.message}`
  }
  return 'Не удалось получить доступ к микрофону.'
}

function pickMimeType(): string | undefined {
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
  for (const type of candidates) {
    if (MediaRecorder.isTypeSupported(type)) return type
  }
  return undefined
}

export function useRecorder() {
  const [phase, setPhase] = useState<RecorderPhase>('idle')
  const [meetingId, setMeetingId] = useState<number | null>(null)
  const [elapsedMs, setElapsedMs] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [isQuiet, setIsQuiet] = useState(false)

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const micStreamRef = useRef<MediaStream | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const rafRef = useRef<number | null>(null)
  const timerRef = useRef<number | null>(null)
  const startedAtRef = useRef<number>(0)
  const meetingIdRef = useRef<number | null>(null)
  const uploadChainRef = useRef<Promise<void>>(Promise.resolve())
  const stopResolveRef = useRef<(() => void) | null>(null)
  const isQuietRef = useRef(false)
  const quietSinceRef = useRef<number | null>(null)
  const loudSinceRef = useRef<number | null>(null)
  const waveRef = useRef(new Float32Array(WAVE_BARS))
  const lastWaveAtRef = useRef(0)

  const cleanupMedia = useCallback(() => {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
    if (timerRef.current != null) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }
    analyserRef.current = null
    if (audioCtxRef.current) {
      void audioCtxRef.current.close().catch(() => {})
      audioCtxRef.current = null
    }
    if (micStreamRef.current) {
      for (const track of micStreamRef.current.getTracks()) track.stop()
      micStreamRef.current = null
    }
    mediaRecorderRef.current = null
    quietSinceRef.current = null
    loudSinceRef.current = null
    isQuietRef.current = false
    waveRef.current.fill(0)
    lastWaveAtRef.current = 0
    setIsQuiet(false)
  }, [])

  useEffect(() => () => cleanupMedia(), [cleanupMedia])

  const enqueueChunk = useCallback((id: number, blob: Blob) => {
    if (blob.size === 0) return
    uploadChainRef.current = uploadChainRef.current
      .then(() => api.uploadChunk(id, blob))
      .then(() => undefined)
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : String(err)
        setError(`Ошибка загрузки аудио: ${msg}`)
      })
  }, [])

  /** Mic → gain → analyser (meter) + MediaStreamDestination (what we record). */
  const startBoostedCapture = useCallback(async (micStream: MediaStream) => {
    const AudioCtx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext })
        .webkitAudioContext
    const ctx = new AudioCtx()
    if (ctx.state === 'suspended') await ctx.resume()

    const source = ctx.createMediaStreamSource(micStream)
    const gain = ctx.createGain()
    gain.gain.value = MIC_GAIN
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 256
    const dest = ctx.createMediaStreamDestination()

    source.connect(gain)
    gain.connect(analyser)
    gain.connect(dest)

    audioCtxRef.current = ctx
    analyserRef.current = analyser

    const data = new Uint8Array(analyser.fftSize)
    const quietLevel = 0.02
    const dwellMs = 1000
    const tick = () => {
      const node = analyserRef.current
      if (!node) return
      node.getByteTimeDomainData(data)
      let peak = 0
      for (let i = 0; i < data.length; i++) {
        const v = Math.abs(data[i]! - 128) / 128
        if (v > peak) peak = v
      }

      const now = performance.now()
      if (now - lastWaveAtRef.current >= WAVE_PUSH_MS) {
        lastWaveAtRef.current = now
        const wave = waveRef.current
        const prev = wave[wave.length - 1] ?? 0
        wave.copyWithin(0, 1)
        wave[wave.length - 1] = prev * 0.22 + peak * 0.78
      }

      if (peak < quietLevel) {
        loudSinceRef.current = null
        if (quietSinceRef.current == null) quietSinceRef.current = now
        if (
          !isQuietRef.current &&
          now - quietSinceRef.current >= dwellMs
        ) {
          isQuietRef.current = true
          setIsQuiet(true)
        }
      } else {
        quietSinceRef.current = null
        if (loudSinceRef.current == null) loudSinceRef.current = now
        if (
          isQuietRef.current &&
          now - loudSinceRef.current >= dwellMs
        ) {
          isQuietRef.current = false
          setIsQuiet(false)
        }
      }

      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)

    return dest.stream
  }, [])

  const start = useCallback(
    async (title: string) => {
      if (phase !== 'idle') return
      setError(null)
      setPhase('starting')
      setElapsedMs(0)
      uploadChainRef.current = Promise.resolve()

      try {
        const meeting = await api.createMeeting(title)
        meetingIdRef.current = meeting.id
        setMeetingId(meeting.id)

        let micStream: MediaStream
        try {
          if (!navigator.mediaDevices?.getUserMedia) {
            throw new Error('mediaDevices unavailable')
          }
          micStream = await navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS)
        } catch (err) {
          setError(micErrorMessage(err))
          setPhase('idle')
          meetingIdRef.current = null
          setMeetingId(null)
          return
        }

        micStreamRef.current = micStream
        const recordStream = await startBoostedCapture(micStream)

        const mimeType = pickMimeType()
        const recorder = mimeType
          ? new MediaRecorder(recordStream, { mimeType })
          : new MediaRecorder(recordStream)
        mediaRecorderRef.current = recorder

        recorder.ondataavailable = (ev: BlobEvent) => {
          const id = meetingIdRef.current
          if (id != null && ev.data.size > 0) {
            enqueueChunk(id, ev.data)
          }
        }

        recorder.onstop = () => {
          if (stopResolveRef.current) {
            const resolve = stopResolveRef.current
            stopResolveRef.current = null
            resolve()
          }
        }

        recorder.start(TIMESLICE_MS)
        startedAtRef.current = Date.now()
        timerRef.current = window.setInterval(() => {
          setElapsedMs(Date.now() - startedAtRef.current)
        }, 250)
        setPhase('recording')
      } catch (err) {
        cleanupMedia()
        const msg = err instanceof Error ? err.message : String(err)
        setError(`Не удалось начать запись: ${msg}`)
        meetingIdRef.current = null
        setMeetingId(null)
        setPhase('idle')
      }
    },
    [cleanupMedia, enqueueChunk, phase, startBoostedCapture],
  )

  const stop = useCallback(async (): Promise<number | null> => {
    if (phase !== 'recording') return null
    setPhase('stopping')
    setError(null)

    const recorder = mediaRecorderRef.current
    const id = meetingIdRef.current
    if (!recorder || id == null) {
      cleanupMedia()
      setPhase('idle')
      return null
    }

    try {
      if (recorder.state !== 'inactive') {
        await new Promise<void>((resolve) => {
          stopResolveRef.current = resolve
          recorder.stop()
          // Safety: if no final dataavailable fires
          window.setTimeout(() => {
            if (stopResolveRef.current) {
              stopResolveRef.current = null
              resolve()
            }
          }, 2000)
        })
      }

      await uploadChainRef.current
      await api.stopMeeting(id)
      cleanupMedia()
      setPhase('idle')
      return id
    } catch (err) {
      cleanupMedia()
      const msg = err instanceof Error ? err.message : String(err)
      setError(`Не удалось остановить запись: ${msg}`)
      setPhase('idle')
      return null
    }
  }, [cleanupMedia, phase])

  return {
    phase,
    meetingId,
    elapsedMs,
    waveSamples: waveRef,
    isQuiet,
    error,
    start,
    stop,
    isRecording: phase === 'recording',
    isBusy: phase === 'starting' || phase === 'stopping',
  }
}
