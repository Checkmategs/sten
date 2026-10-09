#!/usr/bin/env bash
# Прогон пайплайна Sten на вычислительном сервере (GPU).
# Использование: scripts/remote-run.sh путь/к/аудио [имя-результата]
set -euo pipefail

REMOTE="${STEN_REMOTE:-nineone@10.91.0.55}"
AUDIO="${1:?Использование: remote-run.sh путь/к/аудио [имя-результата]}"
NAME="${2:-$(basename "${AUDIO%.*}")}"

echo "1/3 Загрузка аудио на $REMOTE..."
ssh "$REMOTE" 'mkdir -p ~/sten/incoming'
scp -q "$AUDIO" "$REMOTE:sten/incoming/$NAME.audio"

echo "2/3 Обработка на сервере (whisper large-v3 на GPU + qwen2.5:32b)..."
ssh "$REMOTE" "source ~/sten/env.sh && cd ~/sten && \
  STEN_WHISPER_MODEL=large-v3 STEN_WHISPER_COMPUTE=float16 \
  STEN_OLLAMA_MODEL=qwen2.5:32b-instruct \
  .venv/bin/python -m sten.pipeline \"\$HOME/sten/incoming/$NAME.audio\" --out 'data/meetings/$NAME'"

echo "3/3 Скачивание результатов..."
mkdir -p "data/meetings/$NAME-remote"
rsync -az --exclude audio.wav "$REMOTE:~/sten/data/meetings/$NAME/" "data/meetings/$NAME-remote/"

echo "Готово: data/meetings/$NAME-remote/summary.md"
