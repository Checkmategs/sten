from pathlib import Path

WHISPER_MODEL = "medium"
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:7b-instruct"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
