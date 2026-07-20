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


def _process_meeting(meeting_id: int) -> None:
    global _busy_meeting_id
    try:
        db.set_meeting_status(meeting_id, "processing")
        out_dir = Path(db.DATA_DIR) / "meetings" / str(meeting_id)
        audio_path = out_dir / "audio.webm"
        pipeline.run(audio_path, out_dir)
        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        items = [(item["text"], item["category"]) for item in summary["items"]]
        db.replace_items(meeting_id, items)
        db.set_meeting_status(meeting_id, "ready")
    except Exception as exc:
        db.set_meeting_status(meeting_id, "error", error=str(exc)[:500])
    finally:
        with _lock:
            if _busy_meeting_id == meeting_id:
                _busy_meeting_id = None
