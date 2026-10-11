"""Background meeting processing (one at a time)."""

from __future__ import annotations

import json
import re
import threading
import traceback
from pathlib import Path

from sten import db, pipeline

# Same shape as the recorder's defaultMeetingTitle().
_AUTO_MEETING_TITLE = re.compile(r"^Встреча \d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
_TITLE_LIMIT = 200

_lock = threading.Lock()
_busy_meeting_id: int | None = None


class Conflict(Exception):
    """Raised when another meeting is already being processed."""


def adopt_brief_title(meeting: dict) -> str:
    """Use the brief's meeting name instead of the automatic «Встреча date» title.

    A title the user typed stays as it is.
    """
    current = str(meeting.get("title") or "").strip()
    if not _AUTO_MEETING_TITLE.fullmatch(current):
        return current
    meeting_id = int(meeting["id"])
    path = Path(db.DATA_DIR) / "meetings" / str(meeting_id) / "summary.json"
    if not path.is_file():
        return current
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return current
    report = data.get("report")
    if not isinstance(report, dict):
        return current
    title = " ".join(str(report.get("title") or "").split())[:_TITLE_LIMIT]
    if not title or title == current:
        return current
    db.set_meeting_title(meeting_id, title)
    return title


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
    """Read summary.json. Empty items are allowed while the protocol is off.

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
            to_wav16k(db.find_source_audio(meeting_id), wav)

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
        from sten.transcribe import Segment

        db.set_meeting_status(meeting_id, "processing")
        db.set_meeting_progress(
            meeting_id, 4, "Обзор совещания…", pipeline.overall_percent(4, 0.0)
        )
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
        from sten.report import build_report, report_is_blank, report_to_items

        meeting_report = build_report(
            segments,
            on_progress=lambda frac: db.set_meeting_progress(
                meeting_id, 4, "Обзор совещания…", pipeline.overall_percent(4, frac)
            ),
        )
        if report_is_blank(meeting_report):
            raise RuntimeError(
                "Обзор встречи пустой после пересборки. Проверьте транскрипт."
            )
        items = report_to_items(meeting_report)
        pipeline.write_outputs(out_dir, segments, items, meeting_report)
        db.replace_items(
            meeting_id, [(i.text, i.category, i.theme) for i in items]
        )
        stored = db.get_meeting(meeting_id)
        if stored is not None:
            adopt_brief_title(stored)
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
        audio_path = db.find_source_audio(meeting_id)

        def on_stage(step: int, total: int, label: str, percent: int = 0) -> None:
            db.set_meeting_progress(meeting_id, step, label, percent)

        pipeline.run(audio_path, out_dir, on_stage=on_stage)
        items = load_items_from_output(out_dir)
        db.replace_items(meeting_id, items)
        stored = db.get_meeting(meeting_id)
        if stored is not None:
            adopt_brief_title(stored)
        db.set_meeting_status(meeting_id, "ready")
    except Exception as exc:
        traceback.print_exc()
        db.set_meeting_status(meeting_id, "error", error=str(exc)[:500])
    finally:
        with _lock:
            if _busy_meeting_id == meeting_id:
                _busy_meeting_id = None
