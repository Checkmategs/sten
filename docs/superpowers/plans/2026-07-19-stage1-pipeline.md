# Sten Stage 1: Audio → Transcript → Summary Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Локальный пайплайн: аудиофайл встречи на входе → русский транскрипт и структурированное саммари по пунктам на выходе, целиком на MacBook без облака.

**Architecture:** Python-пакет `sten` с чистыми модулями (аудио-конвертация, транскрипция, нарезка, LLM-клиент, саммаризация) и CLI-обёрткой. Транскрипция — `faster-whisper` (модель `medium`, уже скачана). Саммаризация — Ollama HTTP API (`qwen2.5:7b-instruct`, уже скачана) со схемой map-reduce для длинных транскриптов. Whisper и LLM работают последовательно — на 16 ГБ одновременно не живут.

**Tech Stack:** Python 3.12 (venv), faster-whisper, httpx, pytest, ffmpeg (установлен), Ollama (установлен).

## Global Constraints

- Всё on-prem: никаких облачных API, данные не покидают машину.
- Python строго 3.12: `/opt/homebrew/opt/python@3.12/bin/python3.12` (у ctranslate2/faster-whisper нет надёжных колёс под 3.14).
- Модель ASR: `medium` (Systran/faster-whisper-medium, уже в `~/.cache/huggingface/hub`). Ничего не скачивать без явного решения.
- Модель LLM: `qwen2.5:7b-instruct` (уже в `~/.ollama/models`). Ollama-сервер должен быть запущен: `ollama serve` (или приложение Ollama).
- Язык контента и промптов — русский. Категории пунктов — англ. идентификаторы: `decision`, `task`, `topic`, `question`.
- Папка `data/` не коммитится (в `.gitignore`).
- Каждая задача заканчивается прогоном тестов и коммитом.

---

### Task 1: Каркас проекта

**Files:**
- Create: `requirements.txt`, `README.md`, `.gitignore`, `sten/__init__.py`, `sten/config.py`, `tests/__init__.py`

**Interfaces:**
- Produces: пакет `sten`, модуль `sten.config` с константами `WHISPER_MODEL: str`, `OLLAMA_URL: str`, `OLLAMA_MODEL: str`, `DATA_DIR: Path`. Все последующие задачи импортируют отсюда.

- [ ] **Step 1: Создать venv и файлы каркаса**

```bash
cd /Users/georgecloud/Documents/91/Sten
/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv .venv
```

`.gitignore`:

```
.venv/
data/
__pycache__/
*.pyc
.pytest_cache/
```

`requirements.txt`:

```
faster-whisper
httpx
pytest
```

`sten/__init__.py` и `tests/__init__.py` — пустые файлы.

`sten/config.py`:

```python
from pathlib import Path

WHISPER_MODEL = "medium"
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:7b-instruct"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
```

`README.md`:

```markdown
# Sten

Локальный пайплайн протоколирования встреч: аудио → транскрипт (русский) → саммари по пунктам. Всё on-prem: faster-whisper + Ollama, данные не покидают машину.

## Требования

- macOS, Apple Silicon
- ffmpeg (`brew install ffmpeg`)
- Ollama с моделью `qwen2.5:7b-instruct` (`ollama pull qwen2.5:7b-instruct`)
- Python 3.12

## Установка

    /opt/homebrew/opt/python@3.12/bin/python3.12 -m venv .venv
    .venv/bin/pip install -r requirements.txt

## Запуск

    ollama serve   # в отдельном терминале, если не запущено приложение Ollama
    .venv/bin/python -m sten.pipeline путь/к/встрече.m4a

Результаты — в `data/meetings/<имя-файла>/`: `transcript.txt`, `transcript.json`, `summary.json`, `summary.md`.

## Тесты

    .venv/bin/pytest                    # быстрые
    .venv/bin/pytest -m integration     # интеграционные (нужны ffmpeg и Ollama)
```

- [ ] **Step 2: Установить зависимости и проверить импорт**

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/python -c "import faster_whisper, httpx; from sten.config import WHISPER_MODEL; print('ok', WHISPER_MODEL)"
```

Expected: `ok medium` (и без ошибок установки; если ctranslate2 не встанет — остановиться и разобраться, это блокер).

- [ ] **Step 3: Настроить pytest-маркер integration**

Create `pytest.ini`:

```ini
[pytest]
markers =
    integration: медленные тесты, требующие ffmpeg/Ollama/моделей
addopts = -m "not integration"
```

(По умолчанию интеграционные тесты пропускаются; запуск: `pytest -m integration`.)

- [ ] **Step 4: Commit**

```bash
git add .gitignore requirements.txt README.md pytest.ini sten tests
git commit -m "chore: project scaffold with config and test markers"
```

---

### Task 2: Конвертация аудио (ffmpeg → WAV 16 кГц моно)

**Files:**
- Create: `sten/audio.py`
- Test: `tests/test_audio.py`

**Interfaces:**
- Consumes: ничего из проекта (только ffmpeg в PATH).
- Produces: `sten.audio.to_wav16k(src: Path, dst: Path) -> Path` — конвертирует любой аудиофайл в WAV 16 кГц моно PCM s16le, возвращает `dst`. Бросает `RuntimeError` с stderr ffmpeg при ошибке.

- [ ] **Step 1: Write the failing test**

`tests/test_audio.py`:

```python
import subprocess
import wave
from pathlib import Path

import pytest

from sten.audio import to_wav16k


@pytest.mark.integration
def test_to_wav16k_converts_to_16k_mono(tmp_path: Path):
    src = tmp_path / "tone.m4a"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-ar", "44100", "-ac", "2", str(src)],
        check=True, capture_output=True,
    )
    dst = tmp_path / "out.wav"
    result = to_wav16k(src, dst)
    assert result == dst
    with wave.open(str(dst)) as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1


@pytest.mark.integration
def test_to_wav16k_raises_on_bad_input(tmp_path: Path):
    src = tmp_path / "garbage.m4a"
    src.write_bytes(b"not audio at all")
    with pytest.raises(RuntimeError):
        to_wav16k(src, tmp_path / "out.wav")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest -m integration tests/test_audio.py -v`
Expected: FAIL / ERROR с `ModuleNotFoundError: No module named 'sten.audio'`

- [ ] **Step 3: Write minimal implementation**

`sten/audio.py`:

```python
import subprocess
from pathlib import Path


def to_wav16k(src: Path, dst: Path) -> Path:
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src),
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr[-500:]}")
    return dst
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest -m integration tests/test_audio.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add sten/audio.py tests/test_audio.py
git commit -m "feat: audio conversion to 16kHz mono wav via ffmpeg"
```

---

### Task 3: Транскрипция (faster-whisper)

**Files:**
- Create: `sten/transcribe.py`
- Test: `tests/test_transcribe.py`

**Interfaces:**
- Consumes: `sten.config.WHISPER_MODEL`.
- Produces:
  - `@dataclass Segment: start: float; end: float; text: str` (text без ведущих/хвостовых пробелов);
  - `transcribe(wav: Path, model_name: str = WHISPER_MODEL) -> list[Segment]` — грузит модель, транскрибирует (`language="ru"`), **освобождает модель до возврата** (критично для памяти);
  - `transcript_text(segments: list[Segment]) -> str` — тексты сегментов через `\n`.

- [ ] **Step 1: Write the failing test**

Юнит-тест на чистую функцию + интеграционный на реальную модель с русской речью, синтезированной macOS `say`.

`tests/test_transcribe.py`:

```python
import subprocess
from pathlib import Path

import pytest

from sten.transcribe import Segment, transcript_text


def test_transcript_text_joins_segments():
    segs = [Segment(0.0, 1.0, "Привет."), Segment(1.0, 2.0, "Как дела?")]
    assert transcript_text(segs) == "Привет.\nКак дела?"


def test_transcript_text_empty():
    assert transcript_text([]) == ""


@pytest.mark.integration
def test_transcribe_russian_speech(tmp_path: Path):
    from sten.audio import to_wav16k
    from sten.transcribe import transcribe

    voices = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    if "Milena" not in voices:
        pytest.skip("Russian voice Milena not installed")

    aiff = tmp_path / "speech.aiff"
    subprocess.run(
        ["say", "-v", "Milena", "-o", str(aiff),
         "Мы решили запустить проект в сентябре."],
        check=True,
    )
    wav = to_wav16k(aiff, tmp_path / "speech.wav")
    segments = transcribe(wav)
    text = transcript_text(segments).lower()
    assert "сентябре" in text or "сентябрь" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_transcribe.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'sten.transcribe'`

- [ ] **Step 3: Write minimal implementation**

`sten/transcribe.py`:

```python
import gc
from dataclasses import dataclass
from pathlib import Path

from sten.config import WHISPER_MODEL


@dataclass
class Segment:
    start: float
    end: float
    text: str


def transcribe(wav: Path, model_name: str = WHISPER_MODEL) -> list[Segment]:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="auto", compute_type="int8")
    try:
        raw_segments, _info = model.transcribe(str(wav), language="ru", vad_filter=True)
        return [Segment(s.start, s.end, s.text.strip()) for s in raw_segments]
    finally:
        del model
        gc.collect()


def transcript_text(segments: list[Segment]) -> str:
    return "\n".join(s.text for s in segments)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_transcribe.py -v` — Expected: 2 passed (юнит).
Run: `.venv/bin/pytest -m integration tests/test_transcribe.py -v` — Expected: 1 passed или skipped, если нет голоса Milena. Первый запуск может занять ~минуту (загрузка модели с диска).

- [ ] **Step 5: Commit**

```bash
git add sten/transcribe.py tests/test_transcribe.py
git commit -m "feat: russian transcription via faster-whisper with memory cleanup"
```

---

### Task 4: Нарезка транскрипта для map-reduce

**Files:**
- Create: `sten/chunking.py`
- Test: `tests/test_chunking.py`

**Interfaces:**
- Consumes: `sten.transcribe.Segment`.
- Produces: `chunk_segments(segments: list[Segment], max_chars: int = 6000) -> list[str]` — режет по границам сегментов; каждый чанк ≤ `max_chars` (кроме случая одиночного сегмента длиннее лимита — он становится отдельным чанком целиком); тексты внутри чанка соединяются `\n`; пустой вход → `[]`.

- [ ] **Step 1: Write the failing test**

`tests/test_chunking.py`:

```python
from sten.chunking import chunk_segments
from sten.transcribe import Segment


def seg(text: str) -> Segment:
    return Segment(0.0, 1.0, text)


def test_empty_input():
    assert chunk_segments([]) == []


def test_all_fits_in_one_chunk():
    segs = [seg("Раз."), seg("Два.")]
    assert chunk_segments(segs, max_chars=100) == ["Раз.\nДва."]


def test_splits_on_segment_boundary():
    segs = [seg("а" * 40), seg("б" * 40), seg("в" * 40)]
    chunks = chunk_segments(segs, max_chars=90)
    assert chunks == ["а" * 40 + "\n" + "б" * 40, "в" * 40]
    assert all(len(c) <= 90 for c in chunks)


def test_oversized_single_segment_kept_whole():
    segs = [seg("х" * 200)]
    assert chunk_segments(segs, max_chars=100) == ["х" * 200]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_chunking.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'sten.chunking'`

- [ ] **Step 3: Write minimal implementation**

`sten/chunking.py`:

```python
from sten.transcribe import Segment


def chunk_segments(segments: list[Segment], max_chars: int = 6000) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for s in segments:
        added = len(s.text) if not current else len(s.text) + 1
        if current and current_len + added > max_chars:
            chunks.append("\n".join(current))
            current, current_len = [], 0
            added = len(s.text)
        current.append(s.text)
        current_len += added
    if current:
        chunks.append("\n".join(current))
    return chunks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_chunking.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add sten/chunking.py tests/test_chunking.py
git commit -m "feat: transcript chunking for map-reduce summarization"
```

---

### Task 5: LLM-клиент (Ollama) и парсинг пунктов саммари

**Files:**
- Create: `sten/llm.py`, `sten/items.py`
- Test: `tests/test_items.py`, `tests/test_llm.py`

**Interfaces:**
- Consumes: `sten.config.OLLAMA_URL`, `sten.config.OLLAMA_MODEL`.
- Produces:
  - `sten.llm.generate(prompt: str, *, schema: dict | None = None, model: str = OLLAMA_MODEL) -> str` — POST `/api/generate`, `stream=False`, `options={"temperature": 0.2, "num_ctx": 8192}`; если задана `schema`, передаётся в поле `format` (structured output Ollama). Бросает `RuntimeError` при недоступном сервере или HTTP-ошибке;
  - `sten.items.CATEGORIES = ("decision", "task", "topic", "question")`;
  - `@dataclass sten.items.SummaryItem: text: str; category: str`;
  - `sten.items.ITEMS_SCHEMA: dict` — JSON-схема ответа LLM;
  - `sten.items.parse_items(raw: str) -> list[SummaryItem]` — парсит JSON вида `{"items": [{"text": ..., "category": ...}]}`; неизвестная категория → `"topic"`; пустые/пробельные тексты отбрасываются; невалидный JSON → `ValueError`.

- [ ] **Step 1: Write the failing tests**

`tests/test_items.py`:

```python
import pytest

from sten.items import SummaryItem, parse_items


def test_parses_valid_items():
    raw = '{"items": [{"text": "Запуск в сентябре", "category": "decision"}]}'
    assert parse_items(raw) == [SummaryItem("Запуск в сентябре", "decision")]


def test_unknown_category_becomes_topic():
    raw = '{"items": [{"text": "Что-то", "category": "жалоба"}]}'
    assert parse_items(raw)[0].category == "topic"


def test_blank_text_dropped():
    raw = '{"items": [{"text": "  ", "category": "task"}, {"text": "Дело", "category": "task"}]}'
    assert [i.text for i in parse_items(raw)] == ["Дело"]


def test_invalid_json_raises():
    with pytest.raises(ValueError):
        parse_items("не json")
```

`tests/test_llm.py`:

```python
import pytest

from sten.items import ITEMS_SCHEMA, parse_items
from sten.llm import generate


@pytest.mark.integration
def test_generate_plain_text():
    out = generate("Ответь одним словом: столица Франции?")
    assert "париж" in out.lower()


@pytest.mark.integration
def test_generate_with_schema_returns_parseable_items():
    out = generate(
        "Составь список из одного пункта саммари: команда решила перенести релиз на май. "
        "Категории: decision, task, topic, question.",
        schema=ITEMS_SCHEMA,
    )
    items = parse_items(out)
    assert len(items) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_items.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'sten.items'`

- [ ] **Step 3: Write minimal implementation**

`sten/items.py`:

```python
import json
from dataclasses import dataclass

CATEGORIES = ("decision", "task", "topic", "question")

ITEMS_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                },
                "required": ["text", "category"],
            },
        }
    },
    "required": ["items"],
}


@dataclass
class SummaryItem:
    text: str
    category: str


def parse_items(raw: str) -> list[SummaryItem]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM вернула невалидный JSON: {e}") from e
    items = []
    for entry in data.get("items", []):
        text = str(entry.get("text", "")).strip()
        if not text:
            continue
        category = entry.get("category")
        if category not in CATEGORIES:
            category = "topic"
        items.append(SummaryItem(text, category))
    return items
```

`sten/llm.py`:

```python
import httpx

from sten.config import OLLAMA_MODEL, OLLAMA_URL


def generate(prompt: str, *, schema: dict | None = None, model: str = OLLAMA_MODEL) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": 8192},
    }
    if schema is not None:
        payload["format"] = schema
    try:
        resp = httpx.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=600.0)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise RuntimeError(f"Ollama недоступна ({OLLAMA_URL}): {e}") from e
    return resp.json()["response"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_items.py -v` — Expected: 4 passed.
Убедиться, что Ollama запущена (`ollama serve` в отдельном терминале или приложение Ollama), затем:
Run: `.venv/bin/pytest -m integration tests/test_llm.py -v` — Expected: 2 passed (первый запуск греет модель, до ~минуты).

- [ ] **Step 5: Commit**

```bash
git add sten/llm.py sten/items.py tests/test_llm.py tests/test_items.py
git commit -m "feat: ollama client and structured summary item parsing"
```

---

### Task 6: Саммаризация map-reduce

**Files:**
- Create: `sten/summarize.py`
- Test: `tests/test_summarize.py`

**Interfaces:**
- Consumes: `sten.chunking.chunk_segments`, `sten.llm.generate`, `sten.items.ITEMS_SCHEMA / parse_items / SummaryItem`, `sten.transcribe.Segment`.
- Produces: `summarize(segments: list[Segment]) -> list[SummaryItem]`:
  - 0 сегментов → `[]`;
  - 1 чанк → один вызов LLM со схемой (без map-фазы);
  - >1 чанка → map: свободнотекстовое саммари каждого чанка; reduce: объединённые частичные саммари → LLM со схемой → `parse_items`.

- [ ] **Step 1: Write the failing test**

Юнит-тесты с подменой `generate` через monkeypatch (без реальной LLM) + интеграционный на реальной модели.

`tests/test_summarize.py`:

```python
import pytest

from sten.items import SummaryItem
from sten.transcribe import Segment
from sten import summarize as summarize_mod
from sten.summarize import summarize


def seg(text: str) -> Segment:
    return Segment(0.0, 1.0, text)


def test_empty_transcript_returns_empty():
    assert summarize([]) == []


def test_single_chunk_one_llm_call(monkeypatch):
    calls = []

    def fake_generate(prompt, *, schema=None, model=None):
        calls.append(schema)
        return '{"items": [{"text": "Решили X", "category": "decision"}]}'

    monkeypatch.setattr(summarize_mod, "generate", fake_generate)
    items = summarize([seg("Обсудили и решили X.")])
    assert items == [SummaryItem("Решили X", "decision")]
    assert len(calls) == 1
    assert calls[0] is not None  # schema передана


def test_multi_chunk_map_reduce(monkeypatch):
    calls = []

    def fake_generate(prompt, *, schema=None, model=None):
        calls.append(schema)
        if schema is None:
            return "частичное саммари"
        return '{"items": [{"text": "Итог", "category": "topic"}]}'

    monkeypatch.setattr(summarize_mod, "generate", fake_generate)
    segs = [seg("а" * 4000), seg("б" * 4000)]  # два чанка при max_chars=6000
    items = summarize(segs)
    assert items == [SummaryItem("Итог", "topic")]
    # 2 map-вызова без схемы + 1 reduce со схемой
    assert calls.count(None) == 2
    assert len(calls) == 3


@pytest.mark.integration
def test_summarize_real_llm():
    segs = [
        seg("Коллеги, предлагаю перенести запуск на сентябрь."),
        seg("Согласен. Тогда Иван готовит план миграции к пятнице."),
        seg("Договорились, переносим на сентябрь."),
    ]
    items = summarize(segs)
    assert len(items) >= 1
    joined = " ".join(i.text.lower() for i in items)
    assert "сентябр" in joined
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_summarize.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'sten.summarize'`

- [ ] **Step 3: Write minimal implementation**

`sten/summarize.py`:

```python
from sten.chunking import chunk_segments
from sten.items import ITEMS_SCHEMA, SummaryItem, parse_items
from sten.llm import generate
from sten.transcribe import Segment

_ITEMS_INSTRUCTION = """Ты — секретарь совещания. Составь подробное саммари встречи в виде списка пунктов.
Каждый пункт — законченное утверждение на русском языке, понятное без чтения транскрипта.
Категории пунктов:
- decision — принятое решение;
- task — задача (по возможности укажи кто и к какому сроку);
- question — открытый вопрос или разногласие, оставшееся без решения;
- topic — обсуждённая тема, важный контекст.
Чем больше полезной информации сохранишь, тем лучше. Не выдумывай ничего, чего нет в тексте."""

_MAP_PROMPT = """Ниже фрагмент транскрипта совещания. Кратко, но без потери фактов перескажи его:
зафиксируй решения, задачи (кто/что/когда), обсуждённые темы и открытые вопросы. Пиши по-русски.

Фрагмент:
{chunk}"""

_REDUCE_PROMPT = _ITEMS_INSTRUCTION + """

Ниже — частичные саммари последовательных фрагментов одной встречи. Объедини их в единый список пунктов,
убери дубли и противоречия.

{partials}"""

_SINGLE_PROMPT = _ITEMS_INSTRUCTION + """

Транскрипт встречи:
{chunk}"""


def summarize(segments: list[Segment]) -> list[SummaryItem]:
    chunks = chunk_segments(segments)
    if not chunks:
        return []
    if len(chunks) == 1:
        raw = generate(_SINGLE_PROMPT.format(chunk=chunks[0]), schema=ITEMS_SCHEMA)
        return parse_items(raw)
    partials = [generate(_MAP_PROMPT.format(chunk=c)) for c in chunks]
    joined = "\n\n---\n\n".join(partials)
    raw = generate(_REDUCE_PROMPT.format(partials=joined), schema=ITEMS_SCHEMA)
    return parse_items(raw)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_summarize.py -v` — Expected: 3 passed (юнит).
Run: `.venv/bin/pytest -m integration tests/test_summarize.py -v` — Expected: 1 passed (Ollama должна быть запущена).

- [ ] **Step 5: Commit**

```bash
git add sten/summarize.py tests/test_summarize.py
git commit -m "feat: map-reduce summarization with russian prompts"
```

---

### Task 7: CLI-пайплайн (аудио на входе → файлы на выходе)

**Files:**
- Create: `sten/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: все предыдущие модули.
- Produces:
  - `run(audio_path: Path, out_dir: Path) -> None` — полный пайплайн, пишет в `out_dir`:
    - `transcript.txt` — текст транскрипта;
    - `transcript.json` — `[{"start": float, "end": float, "text": str}, ...]`;
    - `summary.json` — `{"items": [{"text": str, "category": str}, ...]}`;
    - `summary.md` — саммари для чтения человеком, пункты сгруппированы по категориям (русские заголовки: Решения / Задачи / Темы / Открытые вопросы), пустые категории опущены;
  - `render_markdown(items: list[SummaryItem]) -> str` — чистая функция для `summary.md`;
  - CLI: `python -m sten.pipeline <audio> [--out DIR]`; по умолчанию `DIR = data/meetings/<имя файла без расширения>`. Печатает прогресс по этапам и итоговые пути.

- [ ] **Step 1: Write the failing test**

`tests/test_pipeline.py`:

```python
import json
from pathlib import Path

from sten.items import SummaryItem
from sten.pipeline import render_markdown, write_outputs
from sten.transcribe import Segment


def test_render_markdown_groups_by_category():
    items = [
        SummaryItem("Запуск в сентябре", "decision"),
        SummaryItem("Иван готовит план к пятнице", "task"),
        SummaryItem("Бюджет не согласован", "question"),
    ]
    md = render_markdown(items)
    assert md.index("## Решения") < md.index("## Задачи") < md.index("## Открытые вопросы")
    assert "## Темы" not in md  # пустая категория опущена
    assert "- Запуск в сентябре" in md


def test_render_markdown_empty():
    assert "нет пунктов" in render_markdown([]).lower()


def test_write_outputs_creates_all_files(tmp_path: Path):
    segments = [Segment(0.0, 1.5, "Привет всем.")]
    items = [SummaryItem("Поздоровались", "topic")]
    write_outputs(tmp_path, segments, items)

    assert (tmp_path / "transcript.txt").read_text() == "Привет всем."
    tj = json.loads((tmp_path / "transcript.json").read_text())
    assert tj == [{"start": 0.0, "end": 1.5, "text": "Привет всем."}]
    sj = json.loads((tmp_path / "summary.json").read_text())
    assert sj == {"items": [{"text": "Поздоровались", "category": "topic"}]}
    assert "Поздоровались" in (tmp_path / "summary.md").read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_pipeline.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'sten.pipeline'`

- [ ] **Step 3: Write minimal implementation**

`sten/pipeline.py`:

```python
import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from sten.audio import to_wav16k
from sten.config import DATA_DIR
from sten.items import SummaryItem
from sten.summarize import summarize
from sten.transcribe import Segment, transcribe, transcript_text

_CATEGORY_TITLES = [
    ("decision", "Решения"),
    ("task", "Задачи"),
    ("topic", "Темы"),
    ("question", "Открытые вопросы"),
]


def render_markdown(items: list[SummaryItem]) -> str:
    if not items:
        return "# Саммари встречи\n\nНет пунктов.\n"
    lines = ["# Саммари встречи", ""]
    for category, title in _CATEGORY_TITLES:
        matching = [i for i in items if i.category == category]
        if not matching:
            continue
        lines.append(f"## {title}")
        lines.extend(f"- {i.text}" for i in matching)
        lines.append("")
    return "\n".join(lines)


def write_outputs(out_dir: Path, segments: list[Segment], items: list[SummaryItem]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "transcript.txt").write_text(transcript_text(segments))
    (out_dir / "transcript.json").write_text(
        json.dumps([asdict(s) for s in segments], ensure_ascii=False, indent=2)
    )
    (out_dir / "summary.json").write_text(
        json.dumps({"items": [asdict(i) for i in items]}, ensure_ascii=False, indent=2)
    )
    (out_dir / "summary.md").write_text(render_markdown(items))


def run(audio_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print("1/3 Конвертация аудио...")
    wav = to_wav16k(audio_path, out_dir / "audio.wav")

    print("2/3 Транскрипция (whisper medium)...")
    segments = transcribe(wav)
    print(f"    сегментов: {len(segments)}, прошло {time.time() - t0:.0f} c")

    print("3/3 Саммаризация (qwen2.5:7b)...")
    items = summarize(segments)

    write_outputs(out_dir, segments, items)
    print(f"Готово за {time.time() - t0:.0f} c. Результаты: {out_dir}")
    print(f"  {out_dir / 'summary.md'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sten: аудио встречи → транскрипт и саммари")
    parser.add_argument("audio", type=Path, help="путь к аудиофайлу")
    parser.add_argument("--out", type=Path, default=None, help="папка результатов")
    args = parser.parse_args()
    out_dir = args.out or DATA_DIR / "meetings" / args.audio.stem
    run(args.audio, out_dir)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_pipeline.py -v` — Expected: 3 passed.
Run: `.venv/bin/pytest` — Expected: все юнит-тесты проекта passed.

- [ ] **Step 5: Сквозной прогон на синтетическом аудио**

```bash
say -v Milena -o /tmp/sten-demo.aiff "Коллеги, мы решили перенести запуск проекта на сентябрь. Иван подготовит план миграции к пятнице. Вопрос по бюджету остаётся открытым."
.venv/bin/python -m sten.pipeline /tmp/sten-demo.aiff
cat data/meetings/sten-demo/summary.md
```

Expected: в `summary.md` есть решение про сентябрь и задача Ивана.

- [ ] **Step 6: Commit**

```bash
git add sten/pipeline.py tests/test_pipeline.py
git commit -m "feat: end-to-end CLI pipeline audio -> transcript -> summary"
```

---

### Task 8: Гейт качества — реальная встреча

**Files:** нет новых (ручная проверка).

- [ ] **Step 1: Записать или взять реальную встречу**

Любая реальная запись разговора на русском 15+ минут (диктофон телефона подойдёт, формат любой — ffmpeg переварит).

- [ ] **Step 2: Прогнать пайплайн**

```bash
.venv/bin/python -m sten.pipeline путь/к/записи.m4a
```

Зафиксировать время каждого этапа (пайплайн печатает).

- [ ] **Step 3: Оценить качество и принять решение**

Чек-лист:
- Транскрипт: читаем ли, правильно ли распознаны фамилии/термины? Если много ошибок → докачать `large-v3-turbo` (~1.6 ГБ): в `sten/config.py` поменять `WHISPER_MODEL = "large-v3-turbo"`, повторить прогон.
- Саммари: все ли ключевые решения/задачи попали, нет ли выдуманного? Если качество слабое → попробовать более сильную модель в Ollama (обсудить перед скачиванием).
- Время: полный прогон часовой встречи должен укладываться в разумные минуты, не часы.

**Гейт пройден** → пишем план этапа 2 (запись в браузере + экран согласования). **Не пройден** → меняем модели/промпты и повторяем, прежде чем строить UI.
