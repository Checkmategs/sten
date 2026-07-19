import os
from pathlib import Path

WHISPER_MODEL = os.environ.get("STEN_WHISPER_MODEL", "medium")
WHISPER_COMPUTE = os.environ.get("STEN_WHISPER_COMPUTE", "int8")
OLLAMA_URL = os.environ.get("STEN_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("STEN_OLLAMA_MODEL", "qwen2.5:7b-instruct")
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
