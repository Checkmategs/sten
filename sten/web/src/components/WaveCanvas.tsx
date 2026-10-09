import { useEffect, useRef } from 'react'

const VERT = 'attribute vec2 a; void main(){ gl_Position=vec4(a,0.0,1.0); }'
const FRAG = `precision highp float;
uniform float time;
uniform vec2 resolution;
uniform vec2 pointer;
vec3 palette(float t) {
  float g = 0.42 + 0.22 * cos(6.28318 * t);
  return vec3(g);
}
void main() {
  vec2 uv = (gl_FragCoord.xy * 2.0 - resolution.xy) / resolution.y;
  vec2 uv0 = uv;
  vec3 finalColor = vec3(0.0);
  uv = fract(uv * 1.5) - 0.5;
  uv = sin(uv * 0.5) - pointer;
  float d = length(uv) * exp(-length(uv0));
  vec3 col = palette(length(uv0) + time * 0.4);
  d = sin(d * 8.0 + time) / 8.0;
  d = abs(d);
  d = pow(0.02 / d, 2.0);
  finalColor += col * d;
  gl_FragColor = vec4(finalColor, 1.0);
}`

function compile(
  gl: WebGLRenderingContext,
  type: number,
  src: string,
): WebGLShader | null {
  const shader = gl.createShader(type)
  if (!shader) return null
  gl.shaderSource(shader, src)
  gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) return null
  return shader
}

/** Animated wave behind the shell, same shader as Nina. */
export function WaveCanvas() {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const gl = canvas.getContext('webgl', {
      antialias: false,
      alpha: false,
      powerPreference: 'low-power',
    })
    if (!gl) {
      canvas.hidden = true
      return
    }

    const vs = compile(gl, gl.VERTEX_SHADER, VERT)
    const fs = compile(gl, gl.FRAGMENT_SHADER, FRAG)
    const prog = vs && fs ? gl.createProgram() : null
    if (!vs || !fs || !prog) {
      canvas.hidden = true
      return
    }
    gl.attachShader(prog, vs)
    gl.attachShader(prog, fs)
    gl.linkProgram(prog)
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      canvas.hidden = true
      return
    }

    const buf = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, buf)
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]),
      gl.STATIC_DRAW,
    )
    const loc = gl.getAttribLocation(prog, 'a')
    gl.enableVertexAttribArray(loc)
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0)

    const uTime = gl.getUniformLocation(prog, 'time')
    const uRes = gl.getUniformLocation(prog, 'resolution')
    const uPtr = gl.getUniformLocation(prog, 'pointer')
    const pointer = { x: 0, y: 0 }
    const target = { x: 0, y: 0 }
    let time = 0
    let last = performance.now()
    let raf = 0
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const w = Math.max(1, Math.floor(canvas.clientWidth * dpr))
      const h = Math.max(1, Math.floor(canvas.clientHeight * dpr))
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w
        canvas.height = h
        gl.viewport(0, 0, w, h)
      }
    }

    const onMove = (event: PointerEvent) => {
      const rect = canvas.getBoundingClientRect()
      if (!rect.width || !rect.height) return
      target.x = ((event.clientX - rect.left) / rect.width) * 2 - 1
      target.y = -(((event.clientY - rect.top) / rect.height) * 2 - 1)
    }

    const frame = (now: number) => {
      const delta = Math.min(0.05, (now - last) / 1000)
      last = now
      if (!reduce && !document.hidden) time += delta
      if (!document.hidden) {
        const k = 1 - Math.exp(-delta / 0.2)
        pointer.x += (target.x - pointer.x) * k
        pointer.y += (target.y - pointer.y) * k
        resize()
        gl.useProgram(prog)
        gl.uniform1f(uTime, time)
        gl.uniform2f(uRes, canvas.width, canvas.height)
        gl.uniform2f(uPtr, pointer.x, pointer.y)
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
      }
      raf = requestAnimationFrame(frame)
    }

    window.addEventListener('pointermove', onMove, { passive: true })
    raf = requestAnimationFrame(frame)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('pointermove', onMove)
    }
  }, [])

  return <canvas ref={ref} className="app-wave" aria-hidden="true" />
}
