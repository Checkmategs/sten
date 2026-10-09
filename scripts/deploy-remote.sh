#!/usr/bin/env bash
# Deploy Sten web app to the GPU server and (re)start uvicorn.
# Usage: scripts/deploy-remote.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE="${STEN_REMOTE:-nineone@10.91.0.55}"
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

# Stop sten uvicorn on :8000 (fuser alone can no-op; always pkill too)
pkill -f '[u]vicorn sten.api.app:app' 2>/dev/null || true
if command -v fuser >/dev/null 2>&1; then
  fuser -k 8000/tcp >/dev/null 2>&1 || true
fi
for _ in 1 2 3 4 5; do
  ss -lnt | grep -q ':8000 ' || break
  sleep 1
done

mkdir -p logs
nohup scripts/serve.sh >logs/uvicorn.log 2>&1 &
sleep 2
if curl -sf http://127.0.0.1:8000/api/health >/dev/null; then
  echo "uvicorn healthy on 127.0.0.1:8000"
else
  echo "WARNING: health check failed; see ~/sten/logs/uvicorn.log" >&2
  tail -n 40 logs/uvicorn.log >&2 || true
  exit 1
fi

# HTTPS reverse proxy (docker host net so nginx can reach uvicorn on 127.0.0.1).
# Certs persist outside the rsync tree.
mkdir -p "$HOME/sten-http80/certs"
chmod 700 "$HOME/sten-http80" "$HOME/sten-http80/certs"
cp -f scripts/nginx-80.conf "$HOME/sten-http80/default.conf"
CERT="$HOME/sten-http80/certs/cert.pem"
KEY="$HOME/sten-http80/certs/key.pem"
if [ ! -s "$CERT" ] || [ ! -s "$KEY" ] \
  || ! openssl x509 -in "$CERT" -noout -text 2>/dev/null | grep -q '10.91.0.55'; then
  openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 825 \
    -keyout "$KEY" \
    -out "$CERT" \
    -config "$HOME/sten/scripts/tls.cnf"
  echo "Generated self-signed TLS cert for 10.91.0.55"
fi
chmod 600 "$HOME/sten-http80/certs/key.pem"
chmod 644 "$HOME/sten-http80/certs/cert.pem"
docker rm -f sten-http80 >/dev/null 2>&1 || true
# Host network is required: uvicorn binds 127.0.0.1, which a bridge
# host-gateway IP cannot reach. No sudo for iptables.
docker run -d --name sten-http80 --restart unless-stopped --network host \
  -v "$HOME/sten-http80/default.conf:/etc/nginx/conf.d/default.conf:ro" \
  -v "$HOME/sten-http80/certs:/etc/nginx/certs:ro" \
  nginx:alpine >/dev/null
sleep 1
if curl -kfs https://10.91.0.55/sten/api/health >/dev/null; then
  echo "nginx proxy healthy on https://10.91.0.55/"
else
  echo "WARNING: :443 proxy failed" >&2
  docker logs sten-http80 2>&1 | tail -n 20 >&2 || true
fi
REMOTE_EOF

echo "Done. Open https://10.91.0.55/sten/ (accept the certificate warning once)"
