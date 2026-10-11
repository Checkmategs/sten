import { useState, type AnimationEvent, type FormEvent } from 'react'
import { api, type AuthUser } from '../api'
import { WaveCanvas } from '../components/WaveCanvas'

interface LoginPageProps {
  onLogin: (user: AuthUser) => void
}

function errorText(error: unknown): string {
  if (!(error instanceof Error)) return 'Не получилось'
  const json = error.message.match(/\{.*\}$/)
  if (json) {
    try {
      const body = JSON.parse(json[0]) as { detail?: unknown }
      if (typeof body.detail === 'string') return body.detail
    } catch {
      /* keep the fallback */
    }
  }
  return 'Не получилось'
}

export function LoginPage({ onLogin }: LoginPageProps) {
  const [screen, setScreen] = useState<'login' | 'register'>('login')
  const [phase, setPhase] = useState<'idle' | 'out' | 'in'>('idle')
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const openRegister = () => {
    if (busy || phase === 'out' || screen === 'register') return
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduce) {
      setScreen('register')
      setError(null)
      return
    }
    setPhase('out')
  }

  const onFadeEnd = (event: AnimationEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget || event.animationName !== 'login-fade-out') return
    setScreen('register')
    setError(null)
    setPhase('in')
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const user =
        screen === 'register'
          ? await api.register(name.trim(), password)
          : await api.login(name.trim(), password)
      onLogin(user)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="app-shell">
      <WaveCanvas />
      <main className="login-card">
        <div
          className={phase === 'out' ? 'login-stage is-out' : phase === 'in' ? 'login-stage is-in' : 'login-stage'}
          onAnimationEnd={onFadeEnd}
        >
          <h1>{screen === 'login' ? 'Welcome to Sten' : 'Начните работу'}</h1>
          <form onSubmit={(event) => void submit(event)}>
            <input
              name="name"
              autoComplete="username"
              placeholder="Имя пользователя"
              aria-label="Имя пользователя"
              value={name}
              maxLength={40}
              required
              onChange={(event) => setName(event.target.value)}
            />
            <input
              name="password"
              type="password"
              autoComplete={screen === 'login' ? 'current-password' : 'new-password'}
              placeholder="Пароль"
              aria-label="Пароль"
              value={password}
              minLength={6}
              required
              onChange={(event) => setPassword(event.target.value)}
            />
            {error ? (
              <p className="login-error" role="alert">
                {error}
              </p>
            ) : null}
            <button type="submit" className="record-btn record-btn-start" disabled={busy}>
              {screen === 'login' ? 'Войти' : 'Создать аккаунт'}
            </button>
            <button
              type="button"
              className={screen === 'login' ? 'login-register' : 'login-register is-reserved'}
              disabled={busy || screen !== 'login'}
              tabIndex={screen === 'login' ? 0 : -1}
              aria-hidden={screen !== 'login'}
              onClick={openRegister}
            >
              Регистрация
            </button>
          </form>
        </div>
      </main>
    </div>
  )
}
