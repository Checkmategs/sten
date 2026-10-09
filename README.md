# Sten

Локальный пайплайн протоколирования встреч: аудио → транскрипт (русский) → саммари по пунктам → согласование. Всё on-prem: faster-whisper + Ollama, данные не покидают машину.

## Требования

- macOS (локально) или Linux GPU-сервер
- ffmpeg
- Ollama с моделью саммаризации
- Python 3.12
- Node.js 20+ (только для сборки фронтенда)

## Установка

```bash
/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd sten/web && npm install && npm run build && cd ../..
```

## Запуск локально (CLI)

```bash
ollama serve   # в отдельном терминале, если не запущено приложение Ollama
.venv/bin/python -m sten.pipeline путь/к/встрече.m4a
```

Результаты — в `data/meetings/<имя-файла>/`: `transcript.txt`, `transcript.json`, `summary.json`, `summary.md`.

## Запуск локально (веб)

```bash
# терминал 1 — Ollama
ollama serve

# терминал 2 — API + SPA (после npm run build)
.venv/bin/uvicorn sten.api.app:app --host 127.0.0.1 --port 8000
```

Открыть http://127.0.0.1:8000 — запись с микрофона, обработка, согласование пунктов.

Для разработки фронта: `cd sten/web && npm run dev` (Vite проксирует `/api`).

## Деплой на GPU-сервер

Сервер по умолчанию: `nineone@10.91.0.142`, каталог `~/sten`.

```bash
chmod +x scripts/serve.sh scripts/deploy-remote.sh
./scripts/deploy-remote.sh
```

Скрипт:

1. Собирает фронтенд (`sten/web` → `dist`)
2. Синхронизирует код через rsync (без `data/`, `.venv`)
3. Ставит Python-зависимости в удалённый `.venv`
4. Поднимает Ollama при необходимости и перезапускает uvicorn на `0.0.0.0:8000`

URL: **https://10.91.0.142/**

Модели на сервере (через `scripts/serve.sh` / `env.sh`):

- `STEN_WHISPER_MODEL=large-v3`
- `STEN_WHISPER_COMPUTE=float16`
- `STEN_OLLAMA_MODEL=qwen2.5:32b-instruct`

Разовый CLI-прогон на сервере без веб-UI:

```bash
./scripts/remote-run.sh путь/к/аудио [имя-результата]
```

## Тесты

```bash
.venv/bin/pytest                    # быстрые
.venv/bin/pytest -m integration     # интеграционные (нужны ffmpeg и Ollama)
```
