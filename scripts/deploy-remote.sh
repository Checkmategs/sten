#!/usr/bin/env bash
# Deploy Sten web app to the GPU server and (re)start uvicorn.
# Usage: scripts/deploy-remote.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE="${STEN_REMOTE:-nineone@10.91.0.142}"
REMOTE_DIR="${STEN_REMOTE_DIR:-~/sten}"

cd "$ROOT"

echo "1/4 Building frontend..."
(cd sten/web && npm run build)

echo "2/4 Syncing code to $REMOTE:$REMOTE_DIR ..."
rsync -az --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude 'data/' \
  --exclude 'env.sh' \
  --exclude 'logs/' \
  --exclude 'incoming/' \
  --exclude 'node_modules' \
  --exclude '.pytest_cache' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.superpowers' \
  --exclude '*.webm' \
  ./ "$REMOTE:$REMOTE_DIR/"

echo "3/4 Ensuring Python deps (fastapi/uvicorn)..."
ssh "$REMOTE" "cd $REMOTE_DIR && \
  if [ -x .venv/bin/pip ]; then \
    .venv/bin/pip install -q -r requirements.txt; \
  elif [ -x \$HOME/.local/bin/uv ]; then \
    \$HOME/.local/bin/uv pip install --python .venv/bin/python -r requirements.txt; \
  else \
    .venv/bin/python -m ensurepip --upgrade && \
    .venv/bin/pip install -q -r requirements.txt; \
  fi"

echo "4/4 Restarting Ollama (if needed) and uvicorn..."
ssh "$REMOTE" bash -s <<'REMOTE_EOF'
set -euo pipefail
cd ~/sten

# Ollama
if ! pgrep -f '[o]llama serve' >/dev/null 2>&1; then
  nohup ~/ollama/bin/ollama serve >/tmp/sten-ollama.log 2>&1 &
  sleep 1
  echo "Started ollama serve"
else
  echo "Ollama already running"
fi

# Stop only sten uvicorn on :8000
if command -v fuser >/dev/null 2>&1; then
  fuser -k 8000/tcp >/dev/null 2>&1 || true
elif command -v lsof >/dev/null 2>&1; then
  pid=$(lsof -t -iTCP:8000 -sTCP:LISTEN 2>/dev/null || true)
  if [ -n "${pid:-}" ]; then
    kill $pid 2>/dev/null || true
    sleep 1
  fi
else
  pkill -f '[u]vicorn sten.api.app:app' 2>/dev/null || true
  sleep 1
fi

mkdir -p logs
nohup scripts/serve.sh >logs/uvicorn.log 2>&1 &
sleep 2
if curl -sf http://127.0.0.1:8000/api/health >/dev/null; then
  echo "uvicorn healthy on :8000"
else
  echo "WARNING: health check failed; see ~/sten/logs/uvicorn.log" >&2
  tail -n 40 logs/uvicorn.log >&2 || true
  exit 1
fi
REMOTE_EOF

echo "Done. Open http://10.91.0.142:8000"
