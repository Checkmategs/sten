import { useState } from 'react'
import { api, type Item } from '../api'

interface ItemCardProps {
  meetingId: number
  item: Item
  onChanged: () => void
}

/** Single summary item with accept / edit / rewrite controls. */
export function ItemCard({ meetingId, item, onChanged }: ItemCardProps) {
  const [mode, setMode] = useState<'view' | 'edit' | 'rewrite'>('view')
  const [draft, setDraft] = useState(item.text)
  const [objection, setObjection] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const accept = () =>
    void run(() => api.patchItem(meetingId, item.id, { status: 'accepted' }))

  const reopen = () =>
    void run(() => api.patchItem(meetingId, item.id, { status: 'pending' }))

  const saveEdit = () =>
    void run(async () => {
      const text = draft.trim()
      if (!text) throw new Error('Текст не может быть пустым')
      await api.patchItem(meetingId, item.id, { text })
      setMode('view')
    })

  const doRewrite = () =>
    void run(async () => {
      const text = objection.trim()
      if (!text) throw new Error('Укажите суть возражения')
      await api.rewriteItem(meetingId, item.id, { objection: text })
      setObjection('')
      setMode('view')
    })

  const startEdit = () => {
    setDraft(item.text)
    setMode('edit')
    setError(null)
  }

  const startRewrite = () => {
    setObjection('')
    setMode('rewrite')
    setError(null)
  }

  const cancel = () => {
    setMode('view')
    setDraft(item.text)
    setObjection('')
    setError(null)
  }

  return (
    <article
      className={`item-card${item.status === 'accepted' ? ' item-card-accepted' : ''}`}
    >
      {mode === 'edit' ? (
        <textarea
          className="item-card-textarea"
          value={draft}
          disabled={busy}
          onChange={(e) => setDraft(e.target.value)}
          rows={3}
          aria-label="Текст пункта"
        />
      ) : (
        <p className="item-card-text">
          {item.status === 'accepted' ? (
            <span className="item-card-check" aria-hidden="true">
              ✓{' '}
            </span>
          ) : null}
          {item.text}
        </p>
      )}

      {mode === 'rewrite' ? (
        <div className="item-card-rewrite">
          <label className="item-card-label" htmlFor={`obj-${item.id}`}>
            Суть возражения
          </label>
          <textarea
            id={`obj-${item.id}`}
            className="item-card-textarea"
            value={objection}
            disabled={busy}
            onChange={(e) => setObjection(e.target.value)}
            rows={2}
            placeholder="Что не так с формулировкой?"
          />
        </div>
      ) : null}

      <div className="item-card-actions">
        {mode === 'view' && item.status === 'pending' ? (
          <>
            <button
              type="button"
              className="item-btn item-btn-accept"
              disabled={busy}
              onClick={accept}
            >
              Принят
            </button>
            <button
              type="button"
              className="item-btn"
              disabled={busy}
              onClick={startEdit}
            >
              Изменить
            </button>
            <button
              type="button"
              className="item-btn"
              disabled={busy}
              onClick={startRewrite}
            >
              Переформулировать
            </button>
          </>
        ) : null}

        {mode === 'view' && item.status === 'accepted' ? (
          <button
            type="button"
            className="item-btn"
            disabled={busy}
            onClick={reopen}
          >
            Вернуть в обсуждение
          </button>
        ) : null}

        {mode === 'edit' ? (
          <>
            <button
              type="button"
              className="item-btn item-btn-accept"
              disabled={busy}
              onClick={saveEdit}
            >
              Сохранить
            </button>
            <button
              type="button"
              className="item-btn"
              disabled={busy}
              onClick={cancel}
            >
              Отмена
            </button>
          </>
        ) : null}

        {mode === 'rewrite' ? (
          <>
            <button
              type="button"
              className="item-btn item-btn-accept"
              disabled={busy}
              onClick={doRewrite}
            >
              Переформулировать
            </button>
            <button
              type="button"
              className="item-btn"
              disabled={busy}
              onClick={cancel}
            >
              Отмена
            </button>
          </>
        ) : null}
      </div>

      {error ? (
        <p className="item-card-error" role="alert">
          {error}
        </p>
      ) : null}
    </article>
  )
}
