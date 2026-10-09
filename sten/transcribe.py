import gc
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sten.config import WHISPER_COMPUTE, WHISPER_MODEL

# Lighter compute types to try after the requested one runs out of GPU memory.
_LIGHTER_COMPUTE = {
    "float32": ("float16", "int8_float16", "int8"),
    "bfloat16": ("int8_float16", "int8"),
    "float16": ("int8_float16", "int8"),
    "default": ("int8_float16", "int8"),
    "int8_float16": ("int8",),
    "int8": (),
}

_TIME_MARKER_INTERVAL = 300


@dataclass
class Segment:
    start: float
    end: float
    text: str
    speaker: str | None = None


def format_clock(seconds: float) -> str:
    """Format seconds as mm:ss, or h:mm:ss when past one hour."""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def transcript_with_time_markers(
    segments: list[Segment], interval: int = _TIME_MARKER_INTERVAL
) -> str:
    """Transcript lines with a [mm:ss] marker at each 5-minute window that has speech.

    When segments have speakers, consecutive lines from the same speaker are
    merged into turns: ``Спикер 1: …`` then a blank line before the next turn.
    """
    if not segments:
        return ""
    labeled = any(s.speaker for s in segments)
    if labeled:
        from sten.diarize import merge_turns

        pieces = [(t.start, f"{t.speaker}: {t.text}") for t in merge_turns(segments)]
    else:
        pieces = [(s.start, s.text.strip()) for s in segments if s.text.strip()]

    lines: list[str] = []
    last_mark = -1
    for start, text in pieces:
        if not text:
            continue
        mark = int(start // interval) * interval
        new_window = mark != last_mark
        if new_window:
            if lines and labeled:
                lines.append("")
            lines.append(f"[{format_clock(mark)}]")
            last_mark = mark
        elif labeled and lines:
            lines.append("")
        lines.append(text)
    return "\n".join(lines)


def is_cuda_oom(exc: BaseException) -> bool:
    return "out of memory" in str(exc).lower()


def gpu_memory_free_mib() -> list[tuple[int, int]]:
    """[(device_index, free_mib), ...] with the most free memory first."""
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=index,memory.free",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    rows: list[tuple[int, int]] = []
    for line in out.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 2:
            continue
        try:
            rows.append((int(parts[0]), int(parts[1])))
        except ValueError:
            continue
    rows.sort(key=lambda item: (-item[1], item[0]))
    return rows


def whisper_device_plan(
    compute_type: str,
    gpus: list[tuple[int, int]] | None = None,
) -> list[tuple[str, int | None, str]]:
    """Load attempts as (device, device_index, compute_type).

    The requested precision runs on the GPU with the most free memory.
    If that raises a CUDA out-of-memory error, the caller tries a lighter
    precision on the same GPU, then int8 on CPU.
    """
    if gpus is None:
        gpus = gpu_memory_free_mib()
    else:
        gpus = sorted(gpus, key=lambda item: (-item[1], item[0]))
    plan: list[tuple[str, int | None, str]] = []
    if gpus:
        index = gpus[0][0]
        plan.append(("cuda", index, compute_type))
        for fallback in _LIGHTER_COMPUTE.get(compute_type, ("int8",)):
            plan.append(("cuda", index, fallback))
    else:
        plan.append(("auto", None, compute_type))
    plan.append(("cpu", None, "int8"))
    unique: list[tuple[str, int | None, str]] = []
    for item in plan:
        if item not in unique:
            unique.append(item)
    return unique


def _load_whisper(model_name: str, device: str, device_index: int | None, compute_type: str):
    from faster_whisper import WhisperModel

    kwargs: dict = {"device": device, "compute_type": compute_type}
    if device_index is not None:
        kwargs["device_index"] = device_index
    return WhisperModel(model_name, **kwargs)


def _transcribe_loaded(
    model,
    wav: Path,
    on_progress: Callable[[float], None] | None,
) -> list[Segment]:
    raw_segments, info = model.transcribe(str(wav), language="ru", vad_filter=True)
    duration = float(getattr(info, "duration", 0.0) or 0.0)
    out: list[Segment] = []
    last_reported = -1.0
    for segment in raw_segments:
        out.append(Segment(segment.start, segment.end, segment.text.strip()))
        if on_progress is None or duration <= 0:
            continue
        frac = min(1.0, float(segment.end) / duration)
        if frac - last_reported >= 0.01 or frac >= 1.0:
            last_reported = frac
            on_progress(frac)
    if on_progress is not None and last_reported < 1.0:
        on_progress(1.0)
    return out


def transcribe(
    wav: Path,
    model_name: str = WHISPER_MODEL,
    on_progress: Callable[[float], None] | None = None,
) -> list[Segment]:
    last_oom: BaseException | None = None
    for device, device_index, compute_type in whisper_device_plan(WHISPER_COMPUTE):
        where = device if device_index is None else f"{device}:{device_index}"
        print(f"    whisper {model_name} на {where}, {compute_type}", flush=True)
        model = None
        try:
            model = _load_whisper(model_name, device, device_index, compute_type)
            return _transcribe_loaded(model, wav, on_progress)
        except Exception as exc:
            if device == "cpu" or not is_cuda_oom(exc):
                raise
            last_oom = exc
            print(
                f"    на GPU не хватило памяти ({where}, {compute_type}), пробую иначе",
                flush=True,
            )
        finally:
            if model is not None:
                del model
            gc.collect()
    if last_oom is not None:
        raise last_oom
    raise RuntimeError("Не удалось загрузить модель распознавания")


def transcript_text(segments: list[Segment]) -> str:
    """Plain lines if no speakers; otherwise merged turns with labels."""
    if not segments:
        return ""
    if not any(s.speaker for s in segments):
        return "\n".join(s.text for s in segments)

    from sten.diarize import merge_turns

    turns = merge_turns(segments)
    return "\n\n".join(f"{t.speaker}: {t.text}" for t in turns)
