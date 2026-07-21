import gc
from dataclasses import dataclass
from pathlib import Path

from sten.config import WHISPER_COMPUTE, WHISPER_MODEL


@dataclass
class Segment:
    start: float
    end: float
    text: str
    speaker: str | None = None


def transcribe(wav: Path, model_name: str = WHISPER_MODEL) -> list[Segment]:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="auto", compute_type=WHISPER_COMPUTE)
    try:
        raw_segments, _info = model.transcribe(str(wav), language="ru", vad_filter=True)
        return [Segment(s.start, s.end, s.text.strip()) for s in raw_segments]
    finally:
        del model
        gc.collect()


def transcript_text(segments: list[Segment]) -> str:
    """Plain lines if no speakers; otherwise merged turns with labels."""
    if not segments:
        return ""
    if not any(s.speaker for s in segments):
        return "\n".join(s.text for s in segments)

    from sten.diarize import merge_turns

    turns = merge_turns(segments)
    return "\n\n".join(f"{t.speaker}: {t.text}" for t in turns)
