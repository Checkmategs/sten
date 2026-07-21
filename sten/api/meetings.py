"""Meeting and audio HTTP routes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from sten import db
from sten.api.processing import (
    Conflict,
    is_busy,
    start_diarize,
    start_processing,
    start_resummarize,
)
from sten.config import DATA_DIR
from sten.elaborate import elaborate_item, relevant_excerpt
from sten.rewrite import rewrite_item

router = APIRouter(prefix="/api")


class CreateMeetingBody(BaseModel):
    title: str


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


@router.get("/health")
def health() -> dict:
    return {"ok": True}


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
    from sten.transcribe import Segment, transcript_text

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

    if tt.exists():
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