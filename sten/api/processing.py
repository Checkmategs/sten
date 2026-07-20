"""Background meeting processing (one at a time)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from sten import db, pipeline

_lock = threading.Lock()
_busy_meeting_id: int | None = None


class Conflict(Exception):
    """Raised when another meeting is already being processed."""


def start_processing(meeting_id: int) -> None:
    """Start pipeline for meeting_id in a background thread.

    Raises Conflict if another meeting is already being processed.
    """
    global _busy_meeting_id
    with _lock:
        if _busy_meeting_id is not None and _busy_meeting_id != meeting_id:
            raise Conflict(f"busy with meeting {_busy_meeting_id}")
        _busy_meeting_id = meeting_id

    thread = threading.Thread(
        target=_process_meeting, args=(meeting_id,), daemon=True
    )
    thread.start()


def load_items_from_output(out_dir: Path) -> list[tuple[str, str, str]]:
    """Read summary.json; raise RuntimeError if transcript or items are empty.

    Returns list of (text, category, theme).
    """
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    items = [
        (
            item["text"],
            item["category"],
            str(item.get("theme", "")).strip() or "Общее",
        )
        for item in summary.get("items", [])
    ]
    transcript = (out_dir / "transcript.txt").read_text(encoding="utf-8").strip()
    if not transcript:
        raise RuntimeError(
            "В записи не распознана речь. Проверьте, что выбран нужный микрофон "
            "и на записи есть голос (хотя бы 20–30 секунд разговора)."
        )
    if not items:
        raise RuntimeError(
            "Речь распознана, но пункты саммари пустые. Попробуйте записать дольше."
        )
    return items


def start_resummarize(meeting_id: int) -> None:
    """Re-run summarization from existing transcript (no whisper). Raises Conflict."""
    global _busy_meeting_id
    with _lock:
        if _busy_meeting_id is not None and _busy_meeting_id != meeting_id:
            raise Conflict(f"busy with meeting {_busy_meeting_id}")
        _busy_meeting_id = meeting_id

    thread = threading.Thread(
        target=_resummarize_meeting, args=(meeting_id,), daemon=True
    )
    thread.start()


def _resummarize_meeting(meeting_id: int) -> None:
    global _busy_meeting_id
    try:
        from sten.summarize import summarize
        from sten.transcribe import Segment

        db.set_meeting_status(meeting_id, "processing")
        out_dir = Path(db.DATA_DIR) / "meetings" / str(meeting_id)
        tj = out_dir / "transcript.json"
        if not tj.exists():
            raise RuntimeError("Нет транскрипта — сначала нужна полная обработка записи")
        raw = json.loads(tj.read_text(encoding="utf-8"))
        segments = [Segment(s["start"], s["end"], s["text"]) for s in raw]
        items = summarize(segments)
        if not items:
            raise RuntimeError(
                "Пункты саммари пустые после пересборки. Проверьте транскрипт."
            )
        pipeline.write_outputs(out_dir, segments, items)
        db.replace_items(
            meeting_id, [(i.text, i.category, i.theme) for i in items]
        )
        db.set_meeting_status(meeting_id, "ready")
    except Exception as exc:
        db.set_meeting_status(meeting_id, "error", error=str(exc)[:500])
    finally:
        with _lock:
            if _busy_meeting_id == meeting_id:
                _busy_meeting_id = None


def _process_meeting(meeting_id: int) -> None:
    global _busy_meeting_id
    try:
        db.set_meeting_status(meeting_id, "processing")
        out_dir = Path(db.DATA_DIR) / "meetings" / str(meeting_id)
        audio_path = out_dir / "audio.webm"
        pipeline.run(audio_path, out_dir)
        items = load_items_from_output(out_dir)
        db.replace_items(meeting_id, items)
        db.set_meeting_status(meeting_id, "ready")
    except Exception as exc:
        db.set_meeting_status(meeting_id, "error", error=str(exc)[:500])
    finally:
        with _lock:
            if _busy_meeting_id == meeting_id:
                _busy_meeting_id = None
