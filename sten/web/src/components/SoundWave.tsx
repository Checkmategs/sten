import { useEffect, useRef, type RefObject } from 'react'

interface SoundWaveProps {
  samplesRef: RefObject<Float32Array | null>
}

/** Live mic envelope drawn as centered bars, no backing plate. */
export function SoundWave({ samplesRef }: SoundWaveProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    let raf = 0

    const draw = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const width = canvas.clientWidth
      const height = canvas.clientHeight
      const pxW = Math.max(1, Math.floor(width * dpr))
      const pxH = Math.max(1, Math.floor(height * dpr))
      if (canvas.width !== pxW || canvas.height !== pxH) {
        canvas.width = pxW
        canvas.height = pxH
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, width, height)

      const samples = samplesRef.current
      const count = samples?.length ?? 72
      const gap = 3
      const barW = Math.max(2, (width - gap * (count - 1)) / count)
      const mid = height / 2
      ctx.fillStyle = 'rgba(255, 255, 255, 0.92)'

      for (let i = 0; i < count; i++) {
        const raw = Math.min(1, Math.abs(samples?.[i] ?? 0))
        const shaped = Math.pow(raw, 0.55)
        const barH = Math.max(2, shaped * height * 0.92)
        const x = i * (barW + gap)
        const y = mid - barH / 2
        const radius = Math.min(barW / 2, barH / 2)
        ctx.beginPath()
        ctx.roundRect(x, y, barW, barH, radius)
        ctx.fill()
      }

      raf = requestAnimationFrame(draw)
    }

    raf = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(raf)
  }, [samplesRef])

  return <canvas ref={canvasRef} className="record-wave" aria-hidden="true" />
}
