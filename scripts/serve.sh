#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source env.sh 2>/dev/null || true
# Fallback CUDA libs from the venv (faster-whisper / ctranslate2) if env.sh is absent.
SP=".venv/lib/python3.12/site-packages"
if [ -d "$SP/nvidia/cublas/lib" ]; then
  export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:+$LD_LIBRARY_PATH:}$SP/nvidia/cublas/lib:$SP/nvidia/cudnn/lib"
fi
export STEN_WHISPER_MODEL="${STEN_WHISPER_MODEL:-large-v3}"
export STEN_WHISPER_COMPUTE="${STEN_WHISPER_COMPUTE:-float16}"
export STEN_OLLAMA_MODEL="${STEN_OLLAMA_MODEL:-qwen2.5:32b-instruct}"
export STEN_OLLAMA_URL="${STEN_OLLAMA_URL:-http://localhost:11434}"
exec .venv/bin/uvicorn sten.api.app:app --host 0.0.0.0 --port 8000
