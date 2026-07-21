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


def is_busy(meeting_id: int) -> bool:
    with _lock:
        return _busy_meeting_id == meeting_id


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


def start_diarize(meeting_id: int) -> None:
    """Run speaker diarization on existing wav+transcript. Raises Conflict."""
    global _busy_meeting_id
    with _lock:
        if _busy_meeting_id is not None and _busy_meeting_id != meeting_id:
            raise Conflict(f"busy with meeting {_busy_meeting_id}")
        _busy_meeting_id = meeting_id

    thread = threading.Thread(
        target=_diarize_meeting, args=(meeting_id,), daemon=True
    )
    thread.start()


def _diarize_meeting(meeting_id: int) -> None:
    global _busy_meeting_id
    try:
        from dataclasses import asdict

        from sten.audio import to_wav16k
        from sten.diarize import diarize_segments
        from sten.transcribe import Segment, transcript_text

        out_dir = Path(db.DATA_DIR) / "meetings" / str(meeting_id)
        tj = out_dir / "transcript.json"
        if not tj.exists():
            raise RuntimeError("Нет транскрипта — сначала нужна полная обработка записи")

        wav = out_dir / "audio.wav"
        if not wav.exists():
            webm = out_dir / "audio.webm"
            if not webm.exists():
                raise RuntimeError("Нет аудиофайла для диаризации")
            to_wav16k(webm, wav)

        raw = json.loads(tj.read_text(encoding="utf-8"))
        segments = [
            Segment(
                float(s["start"]),
                float(s["end"]),
                str(s["text"]),
                s.get("speaker"),
            )
            for s in raw
        ]
        segments = diarize_segments(segments, wav)
        (out_dir / "transcript.txt").write_text(
            transcript_text(segments), encoding="utf-8"
        )
        (out_dir / "transcript.json").write_text(
            json.dumps([asdict(s) for s in segments], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        # Keep meeting status; surface error via a small marker file for the UI poll.
        err_path = Path(db.DATA_DIR) / "meetings" / str(meeting_id) / "diarize_error.txt"
        err_path.write_text(str(exc)[:500], encoding="utf-8")
    else:
        err_path = Path(db.DATA_DIR) / "meetings" / str(meeting_id) / "diarize_error.txt"
        if err_path.exists():
            err_path.unlink()
    finally:
        with _lock:
            if _busy_meeting_id == meeting_id:
                _busy_meeting_id = None


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
        segments = [
            Segment(
                float(s["start"]),
                float(s["end"]),
                str(s["text"]),
                s.get("speaker"),
            )
            for s in raw
        ]
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
