"""Assign pyannote labels to Whisper segments and merge into turns."""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

from sten.transcribe import Segment


@dataclass(frozen=True)
class Turn:
    speaker: str
    start: float
    end: float
    text: str


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def speaker_display_names(raw_labels_in_order: list[str]) -> dict[str, str]:
    """Map SPEAKER_XX → Спикер N by first-appearance order."""
    mapping: dict[str, str] = {}
    n = 1
    for label in raw_labels_in_order:
        if label not in mapping:
            mapping[label] = f"Спикер {n}"
            n += 1
    return mapping


def assign_speakers(
    segments: list[Segment],
    diarization: list[tuple[float, float, str]],
) -> list[Segment]:
    """Attach display speaker names to segments by max time overlap.

    ``diarization`` is a list of (start, end, raw_label) from pyannote.
    Segments with no overlap keep ``speaker=None``.
    """
    if not segments:
        return []
    if not diarization:
        return [
            Segment(s.start, s.end, s.text, speaker=None) for s in segments
        ]

    ordered_labels = [lab for _, _, lab in sorted(diarization, key=lambda x: x[0])]
    names = speaker_display_names(ordered_labels)

    out: list[Segment] = []
    for seg in segments:
        best_label: str | None = None
        best_ov = 0.0
        for start, end, label in diarization:
            ov = _overlap(seg.start, seg.end, start, end)
            if ov > best_ov:
                best_ov = ov
                best_label = label
        speaker = names[best_label] if best_label is not None else None
        out.append(Segment(seg.start, seg.end, seg.text, speaker=speaker))
    return out


def merge_turns(segments: list[Segment]) -> list[Turn]:
    """Merge consecutive segments that share the same speaker into turns."""
    turns: list[Turn] = []
    for seg in segments:
        if not seg.text.strip():
            continue
        speaker = seg.speaker or "Спикер ?"
        if turns and turns[-1].speaker == speaker:
            prev = turns[-1]
            turns[-1] = Turn(
                speaker=prev.speaker,
                start=prev.start,
                end=seg.end,
                text=f"{prev.text} {seg.text}".strip(),
            )
        else:
            turns.append(
                Turn(
                    speaker=speaker,
                    start=seg.start,
                    end=seg.end,
                    text=seg.text.strip(),
                )
            )
    return turns


def apply_diarization(
    segments: list[Segment],
    diarization: list[tuple[float, float, str]],
) -> list[Segment]:
    """Assign speakers and return new segment list (does not call pyannote)."""
    return assign_speakers(segments, diarization)


def _diarize_device(device_index: int | None):
    import torch

    if device_index is not None:
        try:
            torch.zeros(1, device=f"cuda:{device_index}")
            return torch.device("cuda", device_index)
        except Exception:
            return torch.device("cpu")
    # This venv's torch is built for CUDA 13. The server driver only supports
    # 12.8, so a "cuda" device can still fail during init. Fall back to CPU.
    device = torch.device("cpu")
    if torch.cuda.is_available():
        try:
            torch.zeros(1, device="cuda")
            device = torch.device("cuda")
        except Exception:
            device = torch.device("cpu")
    return device


def load_waveform(wav: Path) -> dict:
    """Read a 16-bit PCM wav into the dict pyannote accepts.

    Avoids torchcodec, which fails to load on this machine.
    """
    import numpy as np
    import torch

    with wave.open(str(wav), "rb") as handle:
        channels = handle.getnchannels()
        rate = handle.getframerate()
        width = handle.getsampwidth()
        frames = handle.readframes(handle.getnframes())
    if width != 2:
        raise RuntimeError(f"Ожидался 16-bit wav, получено {width * 8}-bit")
    audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).T
    else:
        audio = audio.reshape(1, -1)
    return {"waveform": torch.from_numpy(audio.copy()), "sample_rate": rate}


def diarize_wav(
    wav: Path, device_index: int | None = None
) -> list[tuple[float, float, str]]:
    """Run pyannote speaker diarization. Returns (start, end, raw_label) list.

    Requires ``HF_TOKEN`` and accepted licenses for the pyannote models.
    """
    from sten.config import DIARIZATION_MODEL, HF_TOKEN

    if not HF_TOKEN:
        raise RuntimeError(
            "Нет HF_TOKEN: задайте токен Hugging Face для pyannote "
            "(и примите лицензии speaker-diarization-3.1 / segmentation-3.0)."
        )

    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained(
        DIARIZATION_MODEL,
        token=HF_TOKEN,
    )
    device = _diarize_device(device_index)
    print(f"    pyannote на {device}", flush=True)
    pipeline.to(device)

    annotation = pipeline(load_waveform(wav))
    # pyannote 3.x may return DiarizeOutput with .speaker_diarization
    if hasattr(annotation, "speaker_diarization"):
        annotation = annotation.speaker_diarization

    result: list[tuple[float, float, str]] = []
    for turn, _, label in annotation.itertracks(yield_label=True):
        result.append((float(turn.start), float(turn.end), str(label)))
    result.sort(key=lambda x: x[0])
    return result


def diarize_segments(segments: list[Segment], wav: Path) -> list[Segment]:
    """Run pyannote on wav and assign speakers to Whisper segments."""
    return apply_diarization(segments, diarize_wav(wav))
