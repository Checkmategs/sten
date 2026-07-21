import { useState } from 'react'
import { api, type Item } from '../api'

interface ItemCardProps {
  meetingId: number
  item: Item
  categoryLabel?: string
  onChanged: () => void
}

/** Single summary item with accept / edit / rewrite / elaborate controls. */
export function ItemCard({
  meetingId,
  item,
  categoryLabel,
  onChanged,
}: ItemCardProps) {
  const [mode, setMode] = useState<'view' | 'edit' | 'rewrite' | 'elaborate'>(
    'view',
  )
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

  const remove = () => {
    if (!window.confirm('Удалить этот пункт?')) return
    void run(() => api.deleteItem(meetingId, item.id))
  }

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

  /** Ask LLM for a draft; user edits, then applies with PATCH. */
  const startElaborate = () =>
    void (async () => {
      setBusy(true)
      setError(null)
      try {
        const suggestion = await api.elaborateItem(meetingId, item.id)
        setDraft(suggestion.text)
        setMode('elaborate')
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      } finally {
        setBusy(false)
      }
    })()

  const applyElaborate = () =>
    void run(async () => {
      const text = draft.trim()
      if (!text) throw new Error('Текст не может быть пустым')
      await api.patchItem(meetingId, item.id, { text })
      setMode('view')
    })

  const cancelElaborate = () => {
    setDraft(item.text)
    setMode('view')
    setError(null)
  }
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

  const showElaborateBtn = mode === 'view'

  return (
    <article
      className={`item-card${item.status === 'accepted' ? ' item-card-accepted' : ''}`}
    >
      {mode === 'view' ? (
        <button
          type="button"
          className="item-btn-trash"
          disabled={busy}
          onClick={remove}
          title="Удалить пункт"
          aria-label="Удалить пункт"
        >
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            <line x1="10" y1="11" x2="10" y2="17" />
            <line x1="14" y1="11" x2="14" y2="17" />
          </svg>
        </button>
      ) : null}

      {categoryLabel ? (
        <span className="item-card-badge">{categoryLabel}</span>
      ) : null}

      {mode === 'edit' || mode === 'elaborate' ? (
        <>
          {mode === 'elaborate' ? (
            <p className="item-card-hint">
              Черновик от нейросети — поправьте, если что-то неверно, затем
              «Применить».
            </p>
          ) : null}
          <textarea
            className="item-card-textarea"
            value={draft}
            disabled={busy}
            onChange={(e) => setDraft(e.target.value)}
            rows={mode === 'elaborate' ? 5 : 3}
            aria-label="Текст пункта"
          />
        </>
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

        {mode === 'elaborate' ? (
          <>
            <button
              type="button"
              className="item-btn item-btn-accept"
              disabled={busy}
              onClick={applyElaborate}
            >
              Применить
            </button>
            <button
              type="button"
              className="item-btn"
              disabled={busy}
              onClick={cancelElaborate}
            >
              Закрыть
            </button>
          </>
        ) : null}

        {showElaborateBtn ? (
          <button
            type="button"
            className="item-btn item-btn-ai"
            disabled={busy}
            onClick={startElaborate}
            title="Уточнить по транскрипту"
          >
            {busy ? 'Уточняю…' : '✦ Уточнить'}
          </button>
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
