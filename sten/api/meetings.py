"""Meeting and audio HTTP routes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from sten import db
from sten.audio import guess_audio_ext
from sten.api.processing import (
    Conflict,
    is_busy,
    start_diarize,
    start_processing,
    start_resummarize,
)
from sten.config import DATA_DIR
from sten.db import MAX_AUDIO_BYTES
from sten.elaborate import elaborate_item, relevant_excerpt
from sten.rewrite import rewrite_item

router = APIRouter(prefix="/api")

_STEP_PERCENT = {1: 10, 2: 40, 3: 70, 4: 90}
_STAGE_TOTAL = 4
_READ_CHUNK = 1_048_576


class CreateMeetingBody(BaseModel):
    title: str


class PatchMeetingBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class PatchItemBody(BaseModel):
    text: str | None = None
    status: Literal["pending", "accepted"] | None = None


class RewriteBody(BaseModel):
    objection: str = Field(min_length=1)


def _require_meeting(meeting_id: int) -> dict:
    meeting = db.get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="meeting not found")
    return meeting


def _require_item(meeting_id: int, item_id: int) -> dict:
    for item in db.list_items(meeting_id):
        if item["id"] == item_id:
            return item
    raise HTTPException(status_code=404, detail="item not found")


def _progress_payload(meeting: dict) -> dict | None:
    status = meeting["status"]
    if status in ("ready", "consensus"):
        return {"step": _STAGE_TOTAL, "total": _STAGE_TOTAL, "percent": 100, "label": "Готово"}
    if status != "processing":
        return None
    step = meeting.get("progress_step")
    label = meeting.get("progress_label")
    stored_percent = meeting.get("progress_percent")
    if step is None:
        return {
            "step": 0,
            "total": _STAGE_TOTAL,
            "percent": 0,
            "label": label or "Обработка…",
        }
    if stored_percent is not None:
        percent = int(stored_percent)
    else:
        percent = _STEP_PERCENT.get(int(step), 0)
    return {
        "step": int(step),
        "total": _STAGE_TOTAL,
        "percent": percent,
        "label": label or "Обработка…",
    }


@router.get("/health")
def health() -> dict:
    return {"ok": True}


def _meeting_visible(meeting: dict, include_id: int | None) -> bool:
    if meeting["status"] != "recording" or meeting["id"] == include_id:
        return True
    try:
        db.find_source_audio(meeting["id"])
    except FileNotFoundError:
        return False
    return True


@router.get("/meetings")
def list_meetings(include_id: int | None = None) -> list[dict]:
    """Newest meetings first. Empty recordings stay hidden unless include_id."""
    return [
        {
            "id": meeting["id"],
            "title": meeting["title"],
            "status": meeting["status"],
            "created_at": meeting["created_at"],
        }
        for meeting in db.list_meetings()
        if _meeting_visible(meeting, include_id)
    ]


@router.post("/meetings")
def create_meeting(body: CreateMeetingBody) -> dict:
    meeting_id = db.create_meeting(body.title)
    meeting = db.get_meeting(meeting_id)
    assert meeting is not None
    return {"id": meeting["id"], "title": meeting["title"], "status": meeting["status"]}


@router.get("/meetings/{meeting_id}")
def get_meeting(meeting_id: int) -> dict:
    meeting = _require_meeting(meeting_id)
    items = db.list_items(meeting_id)
    counts = db.count_item_statuses(meeting_id)
    return {**meeting, "items": items, "counts": counts}


@router.patch("/meetings/{meeting_id}")
def patch_meeting(meeting_id: int, body: PatchMeetingBody) -> dict:
    _require_meeting(meeting_id)
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="empty title")
    db.set_meeting_title(meeting_id, title)
    meeting = _require_meeting(meeting_id)
    return {"id": meeting["id"], "title": meeting["title"], "status": meeting["status"]}


@router.delete("/meetings/{meeting_id}")
def delete_meeting(meeting_id: int) -> dict:
    _require_meeting(meeting_id)
    if is_busy(meeting_id):
        raise HTTPException(status_code=409, detail="meeting is processing")
    db.delete_meeting(meeting_id)
    return {"ok": True, "id": meeting_id}


@router.get("/meetings/{meeting_id}/transcript")
def get_transcript(meeting_id: int) -> dict:
    """Full meeting transcript, optionally split into speaker turns."""
    _require_meeting(meeting_id)
    out_dir = Path(db.DATA_DIR) / "meetings" / str(meeting_id)
    tj = out_dir / "transcript.json"
    tt = out_dir / "transcript.txt"

    if not tj.exists() and not tt.exists():
        return {
            "text": "",
            "available": False,
            "turns": [],
            "diarized": False,
            "busy": is_busy(meeting_id),
            "error": None,
        }

    from sten.diarize import merge_turns
    from sten.transcribe import Segment, transcript_text, transcript_with_time_markers

    segments: list = []
    if tj.exists():
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

    if segments:
        text = transcript_with_time_markers(segments)
    elif tt.exists():
        text = tt.read_text(encoding="utf-8")
    else:
        text = transcript_text(segments)

    turns = [
        {
            "speaker": t.speaker,
            "start": t.start,
            "end": t.end,
            "text": t.text,
        }
        for t in merge_turns(segments)
    ]
    diarized = any(s.speaker for s in segments)
    err_path = out_dir / "diarize_error.txt"
    error = (
        err_path.read_text(encoding="utf-8").strip() if err_path.exists() else None
    )
    return {
        "text": text,
        "available": bool(text.strip()),
        "turns": turns,
        "diarized": diarized,
        "busy": is_busy(meeting_id),
        "error": error or None,
    }


@router.post("/meetings/{meeting_id}/diarize")
def diarize_meeting(meeting_id: int) -> dict:
    """Run speaker diarization on existing audio+transcript (no Whisper/summary)."""
    _require_meeting(meeting_id)
    try:
        start_diarize(meeting_id)
    except Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": meeting_id, "status": "diarizing"}


@router.post("/meetings/{meeting_id}/chunks")
async def upload_chunk(meeting_id: int, request: Request) -> dict:
    _require_meeting(meeting_id)
    data = await request.body()
    db.append_audio_chunk(meeting_id, data)
    return {"bytes_written": len(data)}


@router.post("/meetings/{meeting_id}/audio")
async def upload_audio(
    meeting_id: int, file: UploadFile = File(...)
) -> dict:
    meeting = _require_meeting(meeting_id)
    if meeting["status"] not in ("recording", "error"):
        raise HTTPException(
            status_code=409, detail="meeting is not accepting audio"
        )

    first = await file.read(min(_READ_CHUNK, MAX_AUDIO_BYTES + 1))
    if not first:
        raise HTTPException(status_code=400, detail="empty file")

    ext = guess_audio_ext(file.filename or "", file.content_type or "", first)
    if ext is None:
        raise HTTPException(status_code=400, detail="unsupported audio type")

    dest = db.save_uploaded_audio(meeting_id, ext)
    written = 0
    try:
        with open(dest, "wb") as out:
            out.write(first)
            written += len(first)
            if written > MAX_AUDIO_BYTES:
                raise HTTPException(status_code=413, detail="file too large")
            while True:
                chunk = await file.read(_READ_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_AUDIO_BYTES:
                    raise HTTPException(status_code=413, detail="file too large")
                out.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except Exception:
        dest.unlink(missing_ok=True)
        raise

    db.replace_other_source_audio(meeting_id, dest)

    try:
        start_processing(meeting_id)
    except Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    current = db.get_meeting(meeting_id)
    if current and current["status"] not in ("ready", "error"):
        db.set_meeting_status(meeting_id, "processing")
    meeting = db.get_meeting(meeting_id)
    assert meeting is not None
    return {
        "id": meeting["id"],
        "status": meeting["status"],
        "filename": dest.name,
        "bytes": written,
    }


@router.post("/meetings/{meeting_id}/stop")
def stop_meeting(meeting_id: int) -> dict:
    _require_meeting(meeting_id)
    try:
        start_processing(meeting_id)
    except Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # Immediate status for polling; background thread also sets processing.
    db.set_meeting_status(meeting_id, "processing")
    meeting = db.get_meeting(meeting_id)
    assert meeting is not None
    return {"id": meeting["id"], "status": meeting["status"]}


@router.get("/meetings/{meeting_id}/status")
def meeting_status(meeting_id: int) -> dict:
    meeting = _require_meeting(meeting_id)
    return {
        "status": meeting["status"],
        "error": meeting["error"],
        "counts": db.count_item_statuses(meeting_id),
        "progress": _progress_payload(meeting),
    }


@router.post("/meetings/{meeting_id}/resummarize")
def resummarize_meeting(meeting_id: int) -> dict:
    """Пересобрать саммари из уже готового транскрипта (без повторного Whisper)."""
    _require_meeting(meeting_id)
    try:
        start_resummarize(meeting_id)
    except Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.set_meeting_status(meeting_id, "processing")
    meeting = db.get_meeting(meeting_id)
    assert meeting is not None
    return {"id": meeting["id"], "status": meeting["status"]}


@router.patch("/meetings/{meeting_id}/items/{item_id}")
def patch_item(meeting_id: int, item_id: int, body: PatchItemBody) -> dict:
    _require_meeting(meeting_id)
    _require_item(meeting_id, item_id)
    item = None
    if body.text is not None:
        item = db.update_item_text(item_id, body.text)
    if body.status is not None:
        item = db.set_item_status(item_id, body.status)
    if item is None:
        raise HTTPException(status_code=400, detail="no fields to update")
    if body.status == "accepted":
        db.maybe_mark_consensus(meeting_id)
    return item


@router.delete("/meetings/{meeting_id}/items/{item_id}")
def delete_meeting_item(meeting_id: int, item_id: int) -> dict:
    _require_meeting(meeting_id)
    _require_item(meeting_id, item_id)
    deleted_meeting = db.delete_item(item_id)
    if deleted_meeting is None:
        raise HTTPException(status_code=404, detail="item not found")
    db.maybe_mark_consensus(meeting_id)
    return {"ok": True, "id": item_id}


@router.post("/meetings/{meeting_id}/items/{item_id}/rewrite")
def rewrite_meeting_item(meeting_id: int, item_id: int, body: RewriteBody) -> dict:
    _require_meeting(meeting_id)
    item = _require_item(meeting_id, item_id)
    new_text = rewrite_item(item["text"], body.objection)
    updated = db.update_item_text(item_id, new_text)
    db.maybe_mark_consensus(meeting_id)
    return updated


@router.post("/meetings/{meeting_id}/items/{item_id}/elaborate")
def elaborate_meeting_item(meeting_id: int, item_id: int) -> dict:
    """Предложить уточнённый текст пункта по транскрипту (без записи в БД)."""
    _require_meeting(meeting_id)
    item = _require_item(meeting_id, item_id)
    transcript_path = Path(DATA_DIR) / "meetings" / str(meeting_id) / "transcript.txt"
    transcript = (
        transcript_path.read_text(encoding="utf-8") if transcript_path.exists() else ""
    )
    excerpt = relevant_excerpt(transcript, item["text"])
    new_text = elaborate_item(
        item["text"],
        transcript_excerpt=excerpt,
        theme=str(item.get("theme") or ""),
    )
    if not new_text.strip():
        raise HTTPException(status_code=502, detail="LLM вернула пустой ответ")
    return {
        "id": item["id"],
        "meeting_id": meeting_id,
        "text": new_text,
        "category": item["category"],
        "theme": item.get("theme", "Общее"),
        "status": item["status"],
        "position": item["position"],
    }