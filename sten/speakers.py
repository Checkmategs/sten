"""Speaker registry: rename a label on every turn, delete only when unused."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from sten.transcribe import Segment, transcript_text

SPEAKER_IN_USE = (
    "Этот спикер ещё используется в расшифровке. "
    "Сначала замените его во всех репликах."
)


class SpeakerInUse(Exception):
    """Raised when deleting a speaker who still has turns."""


class SpeakerNotFound(Exception):
    """Raised when the speaker is not in the registry or the transcript."""


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
