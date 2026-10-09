import { useState, type FormEvent } from 'react'
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
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const user =
        mode === 'login'
          ? await api.login(name.trim(), password)
          : await api.register(name.trim(), password)
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
        <h1>Sten</h1>
        <p className="login-lead">Встречи видны только своему пользователю.</p>
        <div className="login-switch" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'login'}
            className={mode === 'login' ? 'is-on' : ''}
            onClick={() => {
              setMode('login')
              setError(null)
            }}
          >
            Войти
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'register'}
            className={mode === 'register' ? 'is-on' : ''}
            onClick={() => {
              setMode('register')
              setError(null)
            }}
          >
            Регистрация
          </button>
        </div>
        <form onSubmit={(event) => void submit(event)}>
          <label>
            Имя
            <input
              name="name"
              autoComplete="username"
              value={name}
              maxLength={40}
              required
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label>
            Пароль
            <input
              name="password"
              type="password"
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              value={password}
              minLength={6}
              required
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {error ? (
            <p className="login-error" role="alert">
              {error}
            </p>
          ) : null}
          <button type="submit" className="record-btn record-btn-start" disabled={busy}>
            {mode === 'login' ? 'Войти' : 'Создать аккаунт'}
          </button>
        </form>
      </main>
    </div>
  )
}
