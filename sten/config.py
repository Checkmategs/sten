import os
from pathlib import Path

WHISPER_MODEL = os.environ.get("STEN_WHISPER_MODEL", "medium")
WHISPER_COMPUTE = os.environ.get("STEN_WHISPER_COMPUTE", "int8")
OLLAMA_URL = os.environ.get("STEN_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("STEN_OLLAMA_MODEL", "qwen2.5:7b-instruct")
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = Path(os.environ.get("STEN_DB_PATH", str(DATA_DIR / "sten.db")))
def project_hf_token_path() -> Path:
    """Gitignored token file in the repo root. Never commit it."""
    return Path(__file__).resolve().parent.parent / ".hf_token"


def read_hf_token() -> str | None:
    """Token for pyannote.

    A non-empty environment variable wins. Otherwise the project file
    ``.hf_token`` is used, then the Hugging Face CLI cache.
    """
    for key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        value = (os.environ.get(key) or "").strip()
        if value:
            return value
    project = project_hf_token_path()
    if project.is_file():
        value = project.read_text(encoding="utf-8").strip()
        if value:
            return value
    cached = Path.home() / ".cache" / "huggingface" / "token"
    if cached.is_file():
        value = cached.read_text(encoding="utf-8").strip()
        if value:
            return value
    return None


HF_TOKEN = read_hf_token()
DIARIZATION_MODEL = os.environ.get(
    "STEN_DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1"
)
