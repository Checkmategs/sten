"""Speaker registry: rename a label on every turn, delete only when unused."""

from __future__ import annotations

import io
import json
import threading
import wave
from dataclasses import asdict
from pathlib import Path

from sten.transcribe import Segment, transcript_text

SAMPLE_SECONDS = 10.0
# A gap this long is a pause, not a breath between words.
PAUSE_SECONDS = 0.4
# pyannote/segmentation-3.0: a frame belongs to a speaker only above this.
_SINGLE_VOICE_THRESHOLD = 0.5
_SPAN_CACHE_VERSION = 1
_SEGMENTATION = None
_CACHE_LOCK = threading.Lock()

SPEAKER_IN_USE = (
    "Этот спикер ещё используется в расшифровке. "
    "Сначала замените его во всех репликах."
)


class SpeakerInUse(Exception):
    """Raised when deleting a speaker who still has turns."""


class SpeakerNotFound(Exception):
    """Raised when the speaker is not in the registry or the transcript."""


class SpeakerSampleMissing(Exception):
    """Raised when this speaker has no speech to clip from the recording."""


def _registry_path(out_dir: Path) -> Path:
    return out_dir / "speakers.json"


def load_segments(out_dir: Path) -> list[Segment]:
    path = out_dir / "transcript.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        Segment(
            float(item["start"]),
            float(item["end"]),
            str(item["text"]),
            item.get("speaker"),
        )
        for item in raw
    ]


def save_segments(out_dir: Path, segments: list[Segment]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "transcript.txt").write_text(transcript_text(segments), encoding="utf-8")
    (out_dir / "transcript.json").write_text(
        json.dumps([asdict(segment) for segment in segments], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def speaker_counts(segments: list[Segment]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for segment in segments:
        name = (segment.speaker or "").strip()
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
    return counts


def read_registry(out_dir: Path) -> list[str] | None:
    path = _registry_path(out_dir)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for name in data.get("speakers") or []:
        text = str(name).strip()
        if text and text not in names:
            names.append(text)
    return names


def write_registry(out_dir: Path, names: list[str]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    unique: list[str] = []
    for name in names:
        text = name.strip()
        if text and text not in unique:
            unique.append(text)
    _registry_path(out_dir).write_text(
        json.dumps({"speakers": unique}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def seed_speakers(out_dir: Path, segments: list[Segment]) -> None:
    write_registry(out_dir, list(speaker_counts(segments)))


def _merge_ranges(
    ranges: list[tuple[float, float]], gap: float
) -> list[tuple[float, float]]:
    if not ranges:
        return []
    ordered = sorted(ranges)
    merged: list[tuple[float, float]] = [ordered[0]]
    for start, end in ordered[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= gap:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _overlaps_any(start: float, end: float, blocked: list[tuple[float, float]]) -> bool:
    for left, right in blocked:
        if _overlap(start, end, left, right) > 0:
            return True
    return False


def _subtract_ranges(
    ranges: list[tuple[float, float]], blocked: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Cut ``blocked`` intervals out of ``ranges``."""
    blocked = _merge_ranges(blocked, 0.0)
    kept: list[tuple[float, float]] = []
    for start, end in ranges:
        cursor = start
        for left, right in blocked:
            if right <= cursor:
                continue
            if left >= end:
                break
            if left > cursor:
                kept.append((cursor, min(left, end)))
            cursor = max(cursor, right)
            if cursor >= end:
                break
        if cursor < end - 1e-3:
            kept.append((cursor, end))
    return [(a, b) for a, b in kept if b - a > 0.05]


def speaker_runs(segments: list[Segment], speaker: str) -> list[tuple[float, float]]:
    """Stretches of this speaker, split on pauses and with other voices removed."""
    name = speaker.strip()
    if not name:
        return []
    own: list[tuple[float, float]] = []
    other: list[tuple[float, float]] = []
    for segment in segments:
        label = (segment.speaker or "").strip()
        start = float(segment.start)
        end = float(segment.end)
        if not label or end <= start:
            continue
        if label == name:
            own.append((start, end))
        else:
            other.append((start, end))
    own = _merge_ranges(own, 0.0)
    other = _merge_ranges(other, 0.0)
    merged: list[tuple[float, float]] = []
    for start, end in own:
        if not merged:
            merged.append((start, end))
            continue
        prev_start, prev_end = merged[-1]
        pause = start - prev_end
        if pause <= PAUSE_SECONDS and not _overlaps_any(prev_end, start, other):
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return _subtract_ranges(merged, other)


def pick_sample_span(
    runs: list[tuple[float, float]], seconds: float = SAMPLE_SECONDS
) -> list[tuple[float, float]]:
    """One window from the longest run, at most ``seconds``, taken from its middle."""
    if seconds <= 0:
        return []
    usable = [(start, end) for start, end in runs if end - start >= 0.2]
    if not usable:
        usable = [(start, end) for start, end in runs if end - start > 0.05]
    if not usable:
        return []
    start, end = max(usable, key=lambda run: (run[1] - run[0], -run[0]))
    length = end - start
    if length <= seconds:
        return [(start, end)]
    offset = (length - seconds) / 2.0
    return [(start + offset, start + offset + seconds)]


def speaker_voice_spans(
    segments: list[Segment], speaker: str, seconds: float = SAMPLE_SECONDS
) -> list[tuple[float, float]]:
    """Up to ``seconds`` from the longest pause-free stretch of this speaker."""
    return pick_sample_span(speaker_runs(segments, speaker), seconds)


def single_voice_spans(
    frames: list[list[float]],
    hop: float,
    origin: float,
    *,
    threshold: float = _SINGLE_VOICE_THRESHOLD,
    min_duration: float = 0.4,
) -> list[tuple[float, float]]:
    """Intervals where exactly one speaker is active, and it stays the same person.

    Overlap and a change of speaker end the interval. ``frames`` are per-speaker
    probabilities from a segmentation model.
    """
    if hop <= 0:
        return []
    spans: list[tuple[float, float]] = []
    index = 0
    count = len(frames)
    while index < count:
        active = [i for i, prob in enumerate(frames[index]) if prob >= threshold]
        if len(active) != 1:
            index += 1
            continue
        speaker = active[0]
        end = index + 1
        while end < count:
            nxt = [i for i, prob in enumerate(frames[end]) if prob >= threshold]
            if nxt != [speaker]:
                break
            end += 1
        start_t = origin + index * hop
        end_t = origin + end * hop
        if end_t - start_t >= min_duration:
            spans.append((start_t, end_t))
        index = end
    return spans


def _segmentation_inference():
    """Cached pyannote segmentation. Local speaker activity, including overlap."""
    global _SEGMENTATION
    if _SEGMENTATION is not None:
        return _SEGMENTATION
    import torch
    from pyannote.audio import Inference, Model

    from sten.config import HF_TOKEN

    if not HF_TOKEN:
        raise RuntimeError(
            "Нет HF_TOKEN: без модели сегментации нельзя гарантировать один голос."
        )
    model = Model.from_pretrained("pyannote/segmentation-3.0", token=HF_TOKEN)
    _SEGMENTATION = Inference(
        model,
        window="sliding",
        duration=10.0,
        step=10.0,
        batch_size=8,
        device=torch.device("cpu"),
    )
    return _SEGMENTATION


def _read_mono(src: wave.Wave_read, start: float, end: float):
    """Float32 mono samples for ``[start, end]`` and the file sample rate."""
    import numpy as np

    rate = src.getframerate()
    channels = src.getnchannels()
    width = src.getsampwidth()
    total = src.getnframes()
    if rate <= 0 or width != 2 or channels <= 0:
        raise wave.Error("unsupported wav")
    first = max(0, int(round(start * rate)))
    last = min(total, int(round(end * rate)))
    if last <= first:
        return rate, np.zeros(0, dtype=np.float32)
    src.setpos(first)
    raw = src.readframes(last - first)
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return rate, np.ascontiguousarray(samples)


def segment_single_voice(
    path: Path, ranges: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Subranges of ``ranges`` where segmentation hears exactly one person."""
    import torch

    usable = [(start, end) for start, end in ranges if end - start >= 0.4]
    if not usable:
        return []
    inference = _segmentation_inference()
    spans: list[tuple[float, float]] = []
    with wave.open(str(path), "rb") as src:
        for start, end in usable:
            _rate, samples = _read_mono(src, start, end)
            if samples.size == 0:
                continue
            if _rate != 16000:
                import torchaudio

                waveform = torchaudio.functional.resample(
                    torch.from_numpy(samples).unsqueeze(0), _rate, 16000
                )
            else:
                waveform = torch.from_numpy(samples).unsqueeze(0)
            feature = inference({"waveform": waveform, "sample_rate": 16000})
            data = feature.data
            chunks = data if getattr(data, "ndim", 1) == 3 else data[None, ...]
            hop = float(feature.sliding_window.duration) / chunks.shape[1]
            step = float(feature.sliding_window.step)
            for index, chunk in enumerate(chunks):
                limit = end - (start + index * step)
                keep = int(min(chunk.shape[0], max(0, round(limit / hop))))
                if keep <= 0:
                    continue
                frames = chunk[:keep].tolist()
                spans.extend(
                    single_voice_spans(frames, hop, start + index * step)
                )
    return spans


def clip_wav(path: Path, spans: list[tuple[float, float]]) -> bytes:
    """Concatenate time ranges from a PCM wav into a new wav."""
    with wave.open(str(path), "rb") as src:
        rate = src.getframerate()
        width = src.getsampwidth()
        channels = src.getnchannels()
        total = src.getnframes()
        if rate <= 0 or width <= 0 or channels <= 0:
            raise wave.Error("invalid wav")
        chunks: list[bytes] = []
        for start, end in spans:
            first = max(0, int(round(start * rate)))
            last = min(total, int(round(end * rate)))
            if last <= first:
                continue
            src.setpos(first)
            chunks.append(src.readframes(last - first))
    if not chunks:
        raise SpeakerSampleMissing(path.name)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as dst:
        dst.setnchannels(channels)
        dst.setsampwidth(width)
        dst.setframerate(rate)
        dst.writeframes(b"".join(chunks))
    return buf.getvalue()


def _span_cache_path(out_dir: Path) -> Path:
    return out_dir / "voice-spans.json"


def _cache_fresh(data: dict, out_dir: Path, wav_path: Path) -> bool:
    transcript = out_dir / "transcript.json"
    if data.get("version") != _SPAN_CACHE_VERSION:
        return False
    try:
        return (
            data.get("transcript_mtime_ns") == transcript.stat().st_mtime_ns
            and data.get("audio_mtime_ns") == wav_path.stat().st_mtime_ns
        )
    except OSError:
        return False


def _cached_voice_span(
    out_dir: Path, wav_path: Path, speaker: str
) -> list[tuple[float, float]] | None:
    path = _span_cache_path(out_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not _cache_fresh(data, out_dir, wav_path):
        return None
    raw = (data.get("speakers") or {}).get(speaker)
    if not isinstance(raw, list):
        return None
    spans: list[tuple[float, float]] = []
    for item in raw:
        if (
            isinstance(item, list)
            and len(item) == 2
            and all(isinstance(value, (int, float)) for value in item)
        ):
            spans.append((float(item[0]), float(item[1])))
    return spans


def _store_voice_span(
    out_dir: Path,
    wav_path: Path,
    speaker: str,
    spans: list[tuple[float, float]],
) -> None:
    path = _span_cache_path(out_dir)
    with _CACHE_LOCK:
        data: dict = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded = {}
            if isinstance(loaded, dict) and _cache_fresh(loaded, out_dir, wav_path):
                data = loaded
        transcript = out_dir / "transcript.json"
        data["version"] = _SPAN_CACHE_VERSION
        data["transcript_mtime_ns"] = transcript.stat().st_mtime_ns
        data["audio_mtime_ns"] = wav_path.stat().st_mtime_ns
        speakers = data.get("speakers")
        if not isinstance(speakers, dict):
            speakers = {}
        speakers[speaker] = [[start, end] for start, end in spans]
        data["speakers"] = speakers
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def render_speaker_sample(out_dir: Path, speaker: str) -> bytes:
    """Up to ten seconds from the longest stretch that is strictly one voice.

    Other speakers' time is removed first. Inside the rest, a segmentation model
    keeps only frames where exactly one person is speaking, so a chorus or a
    quick handoff is not returned as one clip.
    """
    name = speaker.strip()
    segments = load_segments(out_dir)
    runs = speaker_runs(segments, name)
    if not runs:
        registry = read_registry(out_dir) or []
        if name not in registry and speaker_counts(segments).get(name, 0) == 0:
            raise SpeakerNotFound(name)
        raise SpeakerSampleMissing(name)
    wav_path = out_dir / "audio.wav"
    if not wav_path.is_file() or wav_path.stat().st_size == 0:
        raise FileNotFoundError(wav_path)
    pure = _cached_voice_span(out_dir, wav_path, name)
    if pure is None:
        pure = segment_single_voice(wav_path, runs)
        _store_voice_span(out_dir, wav_path, name, pure)
    spans = pick_sample_span(pure)
    if not spans:
        raise SpeakerSampleMissing(name)
    return clip_wav(wav_path, spans)


def list_speakers(out_dir: Path, segments: list[Segment] | None = None) -> list[dict]:
    if segments is None:
        segments = load_segments(out_dir)
    counts = speaker_counts(segments)
    registry = read_registry(out_dir)
    if registry is None:
        registry = list(counts)
    else:
        for name in counts:
            if name not in registry:
                registry.append(name)
    return [{"name": name, "count": counts.get(name, 0)} for name in registry]


def _retarget_report(out_dir: Path, old: str, new: str) -> None:
    path = out_dir / "summary.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    report = data.get("report")
    if not isinstance(report, dict):
        return

    def swap(value: object) -> object:
        return new if value == old else value

    for person in report.get("participants") or []:
        if isinstance(person, dict):
            person["speaker"] = swap(person.get("speaker"))
    for decision in report.get("decisions") or []:
        if isinstance(decision, dict):
            decision["initiator"] = swap(decision.get("initiator"))
    for task in report.get("tasks") or []:
        if isinstance(task, dict):
            task["assignee"] = swap(task.get("assignee"))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def rename_speaker(out_dir: Path, old: str, new: str) -> list[dict]:
    """Rename old on every turn. Merging into an existing name keeps old at count 0."""
    source = old.strip()
    target = new.strip()
    if not source or not target:
        raise ValueError("empty speaker name")
    if len(target) > 80:
        raise ValueError("speaker name too long")
    segments = load_segments(out_dir)
    counts = speaker_counts(segments)
    registry = read_registry(out_dir)
    if registry is None:
        registry = list(counts)
    known = source in registry or counts.get(source, 0) > 0
    if not known:
        raise SpeakerNotFound(source)
    if source == target:
        return list_speakers(out_dir, segments)

    had_turns = counts.get(source, 0) > 0
    for segment in segments:
        if (segment.speaker or "").strip() == source:
            segment.speaker = target
    if target in registry:
        if source not in registry and had_turns:
            registry.append(source)
    else:
        registry = [target if name == source else name for name in registry]
        if target not in registry:
            registry.append(target)
    save_segments(out_dir, segments)
    write_registry(out_dir, registry)
    _retarget_report(out_dir, source, target)
    return list_speakers(out_dir, segments)


def delete_speaker(out_dir: Path, name: str) -> list[dict]:
    speaker = name.strip()
    segments = load_segments(out_dir)
    counts = speaker_counts(segments)
    if counts.get(speaker, 0) > 0:
        raise SpeakerInUse(SPEAKER_IN_USE)
    registry = read_registry(out_dir)
    if registry is None:
        registry = list(counts)
    if speaker not in registry:
        raise SpeakerNotFound(speaker)
    write_registry(out_dir, [item for item in registry if item != speaker])
    return list_speakers(out_dir, segments)
