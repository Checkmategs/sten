# Sten Stage 2: Recording + Live Consensus — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Веб-приложение: ведущий записывает встречу в браузере, после обработки проходит по пунктам саммари на общем экране (принять / править / переформулировать через ИИ) до полного согласия.

**Architecture:** FastAPI на GPU-сервере (`10.91.0.142`) отдаёт API и статику React-фронта. Браузер на Mac пишет микрофон (MediaRecorder, чанки), грузит на сервер, polling статуса обработки. Пайплайн этапа 1 (`sten.pipeline.run`) вызывается в фоновом потоке. Согласование — CRUD пунктов в SQLite + LLM-переформулировка через существующий `sten.llm.generate`. Dev-режим: тот же стек на Mac (`localhost`) с локальными моделями через env.

**Tech Stack:** FastAPI, uvicorn, SQLite (stdlib `sqlite3`), React + Vite + TypeScript, существующий пакет `sten` (pipeline/llm/items).

## Global Constraints

- On-prem: сеть только LAN / localhost; никаких облачных API.
- Модели и compute — через env (`STEN_WHISPER_MODEL`, `STEN_WHISPER_COMPUTE`, `STEN_OLLAMA_URL`, `STEN_OLLAMA_MODEL`); на сервере по умолчанию `large-v3` / `float16` / `qwen2.5:32b-instruct`.
- Язык UI и контента — русский. Категории пунктов: `decision|task|topic|question`.
- Одна встреча обрабатывается за раз (фоновый поток; повторный старт обработки, пока идёт другая — HTTP 409).
- Согласие — простая отметка `accepted` / `pending`; без поимённого учёта.
- `data/` не коммитится. Фронт собирается в `sten/web/dist`, отдаётся FastAPI.
- Python 3.12 venv (на Mac: `.venv`; на сервере: `~/sten/.venv`).
- Тесты: pytest; интеграционные с LLM — `@pytest.mark.integration`.
- Не трогать качество промптов саммари без отдельной задачи — только добавить промпт переформулировки пункта.

## File Structure

```
sten/
  config.py          # + DB_PATH, SERVER defaults (уже есть env)
  db.py              # NEW: schema, connection, meeting/item CRUD
  rewrite.py         # NEW: AI reformulation of one item
  api/
    __init__.py      # NEW
    app.py           # NEW: FastAPI app, CORS, static
    meetings.py      # NEW: routes
    processing.py    # NEW: background pipeline runner
  web/               # NEW: Vite React TS frontend
    package.json
    src/
      api.ts
      App.tsx
      pages/RecordPage.tsx
      pages/ProcessPage.tsx
      pages/ConsensusPage.tsx
tests/
  test_db.py
  test_rewrite.py
  test_api_meetings.py
```

---

### Task 1: SQLite — встречи и пункты

**Files:**
- Create: `sten/db.py`, `tests/test_db.py`
- Modify: `sten/config.py` (добавить `DB_PATH`)

**Interfaces:**
- Produces:
  - `init_db() -> None`
  - `create_meeting(title: str) -> int` — status=`recording`
  - `get_meeting(meeting_id: int) -> dict | None` — keys: id, title, status, created_at, error
  - `list_meetings() -> list[dict]`
  - `set_meeting_status(meeting_id: int, status: str, error: str | None = None) -> None`
  - `append_audio_chunk(meeting_id: int, data: bytes) -> Path` — дописывает в `data/meetings/{id}/audio.webm`
  - `replace_items(meeting_id: int, items: list[tuple[str, str]]) -> None` — (text, category); удаляет старые, пишет новые со status=`pending`, order=0..n
  - `list_items(meeting_id: int) -> list[dict]` — id, meeting_id, text, category, status, position
  - `update_item_text(item_id: int, text: str) -> dict`
  - `set_item_status(item_id: int, status: str) -> dict` — status in `pending|accepted`
  - `count_item_statuses(meeting_id: int) -> dict[str, int]`

Statuses встречи: `recording | uploading | processing | ready | consensus | error`.

- [ ] **Step 1: Write failing tests**

`tests/test_db.py`:

```python
from pathlib import Path

import pytest

from sten import db


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "sten.db")
    monkeypatch.setattr(db, "DATA_DIR", tmp_path / "data")
    db.init_db()
    return tmp_path


def test_create_and_get_meeting(isolated_db):
    mid = db.create_meeting("Стендап")
    m = db.get_meeting(mid)
    assert m["title"] == "Стендап"
    assert m["status"] == "recording"


def test_append_audio_chunk_creates_file(isolated_db):
    mid = db.create_meeting("A")
    p = db.append_audio_chunk(mid, b"abc")
    p2 = db.append_audio_chunk(mid, b"def")
    assert p == p2
    assert p.read_bytes() == b"abcdef"


def test_replace_and_list_items(isolated_db):
    mid = db.create_meeting("A")
    db.replace_items(mid, [("Решили X", "decision"), ("Сделать Y", "task")])
    items = db.list_items(mid)
    assert [i["text"] for i in items] == ["Решили X", "Сделать Y"]
    assert all(i["status"] == "pending" for i in items)


def test_accept_item_and_counts(isolated_db):
    mid = db.create_meeting("A")
    db.replace_items(mid, [("A", "topic"), ("B", "topic")])
    items = db.list_items(mid)
    db.set_item_status(items[0]["id"], "accepted")
    assert db.count_item_statuses(mid) == {"pending": 1, "accepted": 1}


def test_all_accepted_marks_consensus(isolated_db):
    mid = db.create_meeting("A")
    db.replace_items(mid, [("A", "topic")])
    item = db.list_items(mid)[0]
    db.set_item_status(item["id"], "accepted")
    # helper used by API later — test it here if implemented in db
    db.maybe_mark_consensus(mid)
    assert db.get_meeting(mid)["status"] == "consensus"
```

- [ ] **Step 2: Run tests — expect fail**

Run: `.venv/bin/pytest tests/test_db.py -v`
Expected: FAIL (`No module named 'sten.db'`)

- [ ] **Step 3: Implement**

В `sten/config.py` добавить:

```python
DB_PATH = Path(os.environ.get("STEN_DB_PATH", str(DATA_DIR / "sten.db")))
```

`sten/db.py` — реализация через `sqlite3` с `PRAGMA foreign_keys=ON`. Таблицы:

```sql
CREATE TABLE meetings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  status TEXT NOT NULL,
  error TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  category TEXT NOT NULL,
  status TEXT NOT NULL,
  position INTEGER NOT NULL
);
```

`maybe_mark_consensus(meeting_id)`: если есть пункты и все `accepted` → status встречи `consensus`.

- [ ] **Step 4: Run tests — expect pass**

Run: `.venv/bin/pytest tests/test_db.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add sten/config.py sten/db.py tests/test_db.py
git commit -m "feat: sqlite storage for meetings and consensus items"
```

---

### Task 2: ИИ-переформулировка пункта

**Files:**
- Create: `sten/rewrite.py`, `tests/test_rewrite.py`

**Interfaces:**
- Consumes: `sten.llm.generate`, `sten.items` (не обязательно schema — один объект)
- Produces: `rewrite_item(text: str, objection: str, *, transcript_excerpt: str = "") -> str`

Промпт (русский, дословно):

```
Ты — секретарь совещания. Переформулируй пункт протокола с учётом возражения участника.
Сохрани смысл договорённости, убери двусмысленность. Один абзац на русском, без кавычек и преамбулы.
Если возражение требует исключить пункт — верни пустую строку.

Текущий пункт:
{text}

Возражение:
{objection}

Фрагмент транскрипта (может быть пустым):
{transcript_excerpt}
```

Ответ LLM — сырой текст; `strip()`, убрать обёртку в кавычки если есть.

- [ ] **Step 1: Failing unit test (monkeypatch generate)**

```python
from sten import rewrite as rewrite_mod
from sten.rewrite import rewrite_item


def test_rewrite_calls_llm_and_strips(monkeypatch):
    def fake(prompt, **kwargs):
        assert "Возражение" in prompt
        assert "бюджет" in prompt
        return '  "Новая формулировка"  '

    monkeypatch.setattr(rewrite_mod, "generate", fake)
    assert rewrite_item("Старое", "бюджет не согласован") == "Новая формулировка"
```

- [ ] **Step 2: Run — expect fail**
- [ ] **Step 3: Implement `sten/rewrite.py`**
- [ ] **Step 4: Run — expect pass**
- [ ] **Step 5: Commit** `feat: llm rewrite helper for contested summary items`

---

### Task 3: FastAPI — каркас и meeting/audio routes

**Files:**
- Create: `sten/api/__init__.py`, `sten/api/app.py`, `sten/api/meetings.py`, `sten/api/processing.py`, `tests/test_api_meetings.py`
- Modify: `requirements.txt` (+ `fastapi`, `uvicorn`, `python-multipart`)

**Interfaces (HTTP):**
- `POST /api/meetings` body `{"title": str}` → `{id, title, status}`
- `GET /api/meetings/{id}` → meeting + `items` + `counts`
- `POST /api/meetings/{id}/chunks` — raw body audio bytes (`Content-Type: application/octet-stream`) → `{bytes_written}`
- `POST /api/meetings/{id}/stop` — status → `processing`, запускает фон
- `GET /api/meetings/{id}/status` → `{status, error, counts}`
- `PATCH /api/meetings/{id}/items/{item_id}` body `{"text"?: str, "status"?: "pending"|"accepted"}`
- `POST /api/meetings/{id}/items/{item_id}/rewrite` body `{"objection": str}` → updated item
- `GET /api/health` → `{ok: true}`

**Background processing (`sten/api/processing.py`):**
- Глобальный lock / флаг `_busy_meeting_id`
- `start_processing(meeting_id)`: если busy и другой id → raise Conflict; иначе поток:
  1. status=`processing`
  2. `pipeline.run(audio_path, out_dir)` где `audio_path = data/meetings/{id}/audio.webm` (ffmpeg в pipeline справится), `out_dir = data/meetings/{id}`
  3. прочитать `summary.json`, `replace_items(...)`
  4. status=`ready`
  5. on exception: status=`error`, сохранить `str(e)[:500]`

Startup: `init_db()` в lifespan FastAPI.

- [ ] **Step 1: Install deps + failing API tests with TestClient**

```bash
.venv/bin/pip install fastapi uvicorn python-multipart httpx
```

`tests/test_api_meetings.py` — использовать `tmp_path` monkeypatch `DB_PATH`/`DATA_DIR`, мокать `start_processing` чтобы не гонять whisper.

```python
from fastapi.testclient import TestClient
from sten.api.app import create_app
# fixture: monkeypatch db paths, init_db, client = TestClient(create_app())

def test_create_meeting_and_chunk(client):
    r = client.post("/api/meetings", json={"title": "Тест"})
    assert r.status_code == 200
    mid = r.json()["id"]
    r2 = client.post(f"/api/meetings/{mid}/chunks", content=b"1234",
                     headers={"Content-Type": "application/octet-stream"})
    assert r2.status_code == 200
    assert r2.json()["bytes_written"] == 4
```

Аналогично: stop вызывает mocked start_processing; patch item text/status; rewrite с mocked `rewrite_item`.

- [ ] **Step 2: Run — expect fail**
- [ ] **Step 3: Implement API modules**
- [ ] **Step 4: Run API unit tests — pass; full default suite pass**
- [ ] **Step 5: Commit** `feat: fastapi meeting API with chunk upload and consensus endpoints`

---

### Task 4: Frontend scaffold (Vite React TS)

**Files:**
- Create: `sten/web/` (vite react-ts), `sten/web/src/api.ts`, `sten/web/src/App.tsx`, routes

**Interfaces:**
- `api.ts`: typed fetch helpers matching Task 3 routes; `baseURL = ''` (same origin).
- Routes: `/` → Record, `/m/:id/process` → Process, `/m/:id/consensus` → Consensus.
- Dev proxy in `vite.config.ts`: `/api` → `http://127.0.0.1:8000`.
- FastAPI mounts `sten/web/dist` at `/` (после build); в dev — два процесса.

- [ ] **Step 1: Scaffold**

```bash
cd sten && npm create vite@latest web -- --template react-ts
cd web && npm install && npm install react-router-dom
```

Минимальный `App.tsx` с тремя заглушками страниц + `api.health()` вызов на главной для проверки.

- [ ] **Step 2: Wire static serving in `create_app`** — если `web/dist` существует, `StaticFiles(html=True)`.
- [ ] **Step 3: Smoke** — `npm run build`; поднять uvicorn; curl `/api/health` и `/`.
- [ ] **Step 4: Commit** `feat: react frontend scaffold with api client and routes`

---

### Task 5: Экран записи

**Files:**
- Create/modify: `sten/web/src/pages/RecordPage.tsx`, возможно `useRecorder.ts`

**Поведение:**
- Поле названия (по умолчанию «Встреча YYYY-MM-DD HH:MM»).
- Кнопка «Начать запись» → `POST /api/meetings` → MediaRecorder (`audio/webm;codecs=opus` или browser default).
- Каждые ~2 с (или `ondataavailable` timeslice 2000) — POST chunk.
- Индикатор уровня (AnalyserNode) + таймер мм:сс.
- «Стоп» → остановить recorder, дослать последний chunk, `POST .../stop`, navigate `/m/:id/process`.
- Ошибка микрофона — текст по-русски.

- [ ] **Step 1: Implement RecordPage + useRecorder**
- [ ] **Step 2: Manual check in browser** (разрешить микрофон, увидеть чанки в Network).
- [ ] **Step 3: Commit** `feat: recording page with chunked audio upload`

---

### Task 6: Экран обработки + экран согласования

**Files:**
- `sten/web/src/pages/ProcessPage.tsx`
- `sten/web/src/pages/ConsensusPage.tsx`
- `sten/web/src/components/ItemCard.tsx`

**ProcessPage:** poll `GET .../status` каждые 2 с. Показать status. На `ready` → navigate consensus. На `error` — текст ошибки + кнопка «Повторить» (`POST .../stop` снова, если аудио на месте).

**ConsensusPage (крупный шрифт для ТВ):**
- Заголовок встречи, прогресс «Принято X из Y».
- Список пунктов, сгруппированных по категориям (Решения / Задачи / Темы / Открытые вопросы) — как в `render_markdown`.
- У каждого: текст; если `pending` — кнопки «Принят», «Изменить», «Переформулировать»; если `accepted` — галочка, кнопка «Вернуть в обсуждение».
- Изменить: inline textarea + Сохранить (PATCH text).
- Переформулировать: поле «суть возражения» + кнопка → POST rewrite → показать новый текст (остаётся `pending`).
- Когда все accepted — баннер «Протокол согласован» (status уже `consensus` с бэка).

- [ ] **Step 1: Implement ProcessPage**
- [ ] **Step 2: Implement ConsensusPage + ItemCard**
- [ ] **Step 3: Manual UI pass** (можно подставить mock items через API после ручного `replace_items` в sqlite / тестового скрипта без полного whisper).
- [ ] **Step 4: Commit** `feat: processing status and live consensus screens`

---

### Task 7: Деплой на GPU-сервер + сквозной прогон

**Files:**
- Create: `scripts/serve.sh`, `scripts/deploy-remote.sh`
- Modify: `README.md`

**serve.sh (на сервере):**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source env.sh 2>/dev/null || true
export STEN_WHISPER_MODEL="${STEN_WHISPER_MODEL:-large-v3}"
export STEN_WHISPER_COMPUTE="${STEN_WHISPER_COMPUTE:-float16}"
export STEN_OLLAMA_MODEL="${STEN_OLLAMA_MODEL:-qwen2.5:32b-instruct}"
export STEN_OLLAMA_URL="${STEN_OLLAMA_URL:-http://localhost:11434}"
exec .venv/bin/uvicorn sten.api.app:app --host 0.0.0.0 --port 8000
```

`create_app` экспортирует `app = create_app()` на уровне модуля для uvicorn.

**deploy-remote.sh:** rsync кода (exclude data/.venv), `npm run build` локально или на сервере, ssh restart uvicorn (pkill + nohup или systemd unit простым nohup для MVP).

- [ ] **Step 1: Build frontend, deploy, start Ollama+uvicorn on server**
- [ ] **Step 2: С Mac открыть `http://10.91.0.142:8000`, записать 1–2 минуты речи, дождаться саммари, согласовать 2–3 пункта**
- [ ] **Step 3: Commit scripts + README** `feat: remote deploy scripts for stage2 web app`
- [ ] **Step 4: Короткий отчёт в `.superpowers/sdd/progress.md` — URL, время обработки тестовой записи**

---

## Out of scope (этап 3+)

- Архив UI, поиск, воспроизведение аудио в браузере
- Тонкая настройка промптов/моделей
- Auth, HTTPS, systemd unit production-hardening
- Диаризация, голосование с телефонов

## Execution handoff

После сохранения плана: реализовывать через subagent-driven-development (рекомендуется) или inline.
