import os
from pathlib import Path

WHISPER_MODEL = os.environ.get("STEN_WHISPER_MODEL", "medium")
WHISPER_COMPUTE = os.environ.get("STEN_WHISPER_COMPUTE", "int8")
OLLAMA_URL = os.environ.get("STEN_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("STEN_OLLAMA_MODEL", "qwen2.5:7b-instruct")
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = Path(os.environ.get("STEN_DB_PATH", str(DATA_DIR / "sten.db")))
HF_TOKEN = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
DIARIZATION_MODEL = os.environ.get(
    "STEN_DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1"
)
