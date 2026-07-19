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
