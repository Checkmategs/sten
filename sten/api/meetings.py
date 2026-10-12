"""Meeting and audio HTTP routes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from sten import db
from sten.api.auth import require_user
from sten.audio import guess_audio_ext
from sten.api.processing import (
    Conflict,
    adopt_brief_title,
    dialogue_busy,
    is_busy,
    start_dialogue,
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


class RenameSpeakerBody(BaseModel):
    source: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=80)


class MergeSpeakerBody(BaseModel):
    source: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=80)


class DeleteSpeakerBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


_AUDIO_TYPES = {
    ".webm": "audio/webm",
    ".m4a": "audio/mp4",
    ".caf": "audio/x-caf",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".mp4": "video/mp4",
    ".mpeg": "audio/mpeg",
    ".mpga": "audio/mpeg",
    ".m4b": "audio/mp4",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".wav": "audio/wav",
}

def _empty_report() -> dict:
    return {
        "available": False,
        "title": "",
        "summary": "",
        "outcome": "",
        "participants": [],
        "topics": [],
        "decisions": [],
        "tasks": [],
        "text": "",
    }


def _require_meeting(meeting_id: int, user: dict) -> dict:
    meeting = db.get_meeting(meeting_id)
    if meeting is None or meeting.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="meeting not found")
    return meeting


def _public_meeting(meeting: dict) -> dict:
    return {key: value for key, value in meeting.items() if key != "user_id"}


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
def list_meetings(
    include_id: int | None = None, user: dict = Depends(require_user)
) -> list[dict]:
    """Newest meetings first. Empty recordings stay hidden unless include_id."""
    rows = []
    for meeting in db.list_meetings(user["id"]):
        if not _meeting_visible(meeting, include_id):
            continue
        rows.append(
            {
                "id": meeting["id"],
                "title": adopt_brief_title(meeting),
                "status": meeting["status"],
                "created_at": meeting["created_at"],
            }
        )
    return rows


@router.post("/meetings")
def create_meeting(body: CreateMeetingBody, user: dict = Depends(require_user)) -> dict:
    meeting_id = db.create_meeting(body.title, user["id"])
    meeting = db.get_meeting(meeting_id)
    assert meeting is not None
    return {"id": meeting["id"], "title": meeting["title"], "status": meeting["status"]}


@router.get("/meetings/{meeting_id}")
def get_meeting(meeting_id: int, user: dict = Depends(require_user)) -> dict:
    meeting = _require_meeting(meeting_id, user)
    meeting = {**meeting, "title": adopt_brief_title(meeting)}
    items = db.list_items(meeting_id)
    counts = db.count_item_statuses(meeting_id)
    return {**_public_meeting(meeting), "items": items, "counts": counts}


@router.patch("/meetings/{meeting_id}")
def patch_meeting(
    meeting_id: int, body: PatchMeetingBody, user: dict = Depends(require_user)
) -> dict:
    _require_meeting(meeting_id, user)
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="empty title")
    db.set_meeting_title(meeting_id, title)
    meeting = _require_meeting(meeting_id, user)
    return {"id": meeting["id"], "title": meeting["title"], "status": meeting["status"]}


@router.delete("/meetings/{meeting_id}")
def delete_meeting(meeting_id: int, user: dict = Depends(require_user)) -> dict:
    _require_meeting(meeting_id, user)
    if is_busy(meeting_id):
        raise HTTPException(status_code=409, detail="meeting is processing")
    db.delete_meeting(meeting_id)
    return {"ok": True, "id": meeting_id}


@router.get("/meetings/{meeting_id}/transcript")
def get_transcript(meeting_id: int, user: dict = Depends(require_user)) -> dict:
    """Full meeting transcript, optionally split into speaker turns."""
    _require_meeting(meeting_id, user)
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


def _meeting_dir(meeting_id: int) -> Path:
    return Path(db.DATA_DIR) / "meetings" / str(meeting_id)


def _load_report_payload(meeting_id: int) -> dict:
    from sten.report import render_report_text, report_from_dict

    path = _meeting_dir(meeting_id) / "summary.json"
    if not path.exists():
        return _empty_report()
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("report")
    if not isinstance(raw, dict):
        return _empty_report()
    report = report_from_dict(raw)
    payload = report.to_dict()
    payload["available"] = True
    payload["text"] = render_report_text(report)
    return payload


def _source_audio(meeting_id: int) -> Path:
    try:
        return db.find_source_audio(meeting_id)
    except FileNotFoundError:
        wav = _meeting_dir(meeting_id) / "audio.wav"
        if wav.is_file() and wav.stat().st_size > 0:
            return wav
        raise


def _download_name(title: str, ext: str) -> str:
    cleaned = "".join(ch if ch not in '\\/:*?"<>|\n\r\t' else " " for ch in title)
    cleaned = " ".join(cleaned.split()).strip() or "meeting"
    return f"{cleaned[:80]}.{ext}"


def _attachment(content: bytes, media_type: str, filename: str) -> Response:
    encoded = quote(filename)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


def _load_dialogue_payload(meeting_id: int) -> dict:
    from sten.dialogue import dialogue_from_dict, render_dialogue_text

    empty = {
        "available": False,
        "busy": dialogue_busy(meeting_id),
        "error": None,
        "questions": [],
        "text": "",
    }
    path = _meeting_dir(meeting_id) / "summary.json"
    if not path.is_file():
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    error = data.get("dialogue_error")
    if not isinstance(error, str) or not error.strip():
        error = None
    raw = data.get("dialogue")
    if not isinstance(raw, dict):
        empty["error"] = error
        return empty
    dialogue = dialogue_from_dict(raw)
    return {
        "available": True,
        "busy": dialogue_busy(meeting_id),
        "error": error,
        "questions": dialogue.to_dict()["questions"],
        "text": render_dialogue_text(dialogue),
    }


@router.get("/meetings/{meeting_id}/report")
def get_report(meeting_id: int, user: dict = Depends(require_user)) -> dict:
    _require_meeting(meeting_id, user)
    return _load_report_payload(meeting_id)


@router.get("/meetings/{meeting_id}/dialogue")
def get_dialogue(meeting_id: int, user: dict = Depends(require_user)) -> dict:
    _require_meeting(meeting_id, user)
    return _load_dialogue_payload(meeting_id)


@router.post("/meetings/{meeting_id}/dialogue")
def create_dialogue(meeting_id: int, user: dict = Depends(require_user)) -> dict:
    """Собрать карту вопросов по уже готовой расшифровке."""
    _require_meeting(meeting_id, user)
    try:
        start_dialogue(meeting_id)
    except Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _load_dialogue_payload(meeting_id)


@router.get("/meetings/{meeting_id}/audio")
def get_audio(meeting_id: int, user: dict = Depends(require_user)) -> FileResponse:
    _require_meeting(meeting_id, user)
    try:
        path = _source_audio(meeting_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="no audio") from exc
    media = _AUDIO_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media, filename=path.name)


@router.get("/meetings/{meeting_id}/speakers/sample")
def get_speaker_sample(
    meeting_id: int,
    name: str = Query(min_length=1, max_length=80),
    user: dict = Depends(require_user),
) -> FileResponse:
    import wave

    from sten.speakers import SpeakerNotFound, SpeakerSampleMissing, speaker_sample_file

    _require_meeting(meeting_id, user)
    try:
        path = speaker_sample_file(_meeting_dir(meeting_id), name)
    except SpeakerNotFound as exc:
        raise HTTPException(status_code=404, detail="speaker not found") from exc
    except SpeakerSampleMissing as exc:
        raise HTTPException(status_code=404, detail="no sample") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="no audio") from exc
    except wave.Error as exc:
        raise HTTPException(status_code=404, detail="no audio") from exc
    return FileResponse(path, media_type="audio/mpeg")


@router.get("/meetings/{meeting_id}/speakers")
def get_speakers(meeting_id: int, user: dict = Depends(require_user)) -> dict:
    from sten.speakers import list_speakers

    _require_meeting(meeting_id, user)
    return {"speakers": list_speakers(_meeting_dir(meeting_id))}


@router.post("/meetings/{meeting_id}/speakers/rename")
def rename_meeting_speaker(
    meeting_id: int,
    body: RenameSpeakerBody,
    user: dict = Depends(require_user),
) -> dict:
    from sten.speakers import SpeakerNotFound, rename_speaker

    _require_meeting(meeting_id, user)
    if is_busy(meeting_id):
        raise HTTPException(status_code=409, detail="meeting is processing")
    try:
        speakers = rename_speaker(_meeting_dir(meeting_id), body.source, body.target)
    except SpeakerNotFound as exc:
        raise HTTPException(status_code=404, detail="speaker not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"speakers": speakers, "report": _load_report_payload(meeting_id)}


@router.post("/meetings/{meeting_id}/speakers/merge")
def merge_meeting_speakers(
    meeting_id: int,
    body: MergeSpeakerBody,
    user: dict = Depends(require_user),
) -> dict:
    from sten.speakers import SpeakerNotFound, merge_speakers

    _require_meeting(meeting_id, user)
    if is_busy(meeting_id):
        raise HTTPException(status_code=409, detail="meeting is processing")
    try:
        speakers = merge_speakers(_meeting_dir(meeting_id), body.source, body.target)
    except SpeakerNotFound as exc:
        raise HTTPException(status_code=404, detail="speaker not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"speakers": speakers, "report": _load_report_payload(meeting_id)}


@router.post("/meetings/{meeting_id}/speakers/delete")
def delete_meeting_speaker(
    meeting_id: int,
    body: DeleteSpeakerBody,
    user: dict = Depends(require_user),
) -> dict:
    from sten.speakers import SPEAKER_IN_USE, SpeakerInUse, SpeakerNotFound, delete_speaker

    _require_meeting(meeting_id, user)
    if is_busy(meeting_id):
        raise HTTPException(status_code=409, detail="meeting is processing")
    try:
        speakers = delete_speaker(_meeting_dir(meeting_id), body.name)
    except SpeakerInUse as exc:
        raise HTTPException(status_code=409, detail=SPEAKER_IN_USE) from exc
    except SpeakerNotFound as exc:
        raise HTTPException(status_code=404, detail="speaker not found") from exc
    return {"speakers": speakers}


@router.get("/meetings/{meeting_id}/export")
def export_meeting(
    meeting_id: int,
    fmt: Literal["txt", "srt", "docx"] = Query(alias="format"),
    user: dict = Depends(require_user),
) -> Response:
    from sten.exporting import render_docx, render_srt
    from sten.report import report_from_dict
    from sten.speakers import load_segments
    from sten.transcribe import transcript_text

    meeting = _require_meeting(meeting_id, user)
    out_dir = _meeting_dir(meeting_id)
    title = str(meeting["title"])
    if fmt == "txt":
        path = out_dir / "transcript.txt"
        if path.exists():
            text = path.read_text(encoding="utf-8")
        else:
            text = transcript_text(load_segments(out_dir))
        if not text.strip():
            raise HTTPException(status_code=404, detail="no transcript")
        return _attachment(text.encode("utf-8"), "text/plain; charset=utf-8", _download_name(title, "txt"))
    if fmt == "srt":
        segments = load_segments(out_dir)
        if not segments:
            raise HTTPException(status_code=404, detail="no transcript")
        return _attachment(
            render_srt(segments).encode("utf-8"),
            "application/x-subrip; charset=utf-8",
            _download_name(title, "srt"),
        )
    payload = _load_report_payload(meeting_id)
    if not payload["available"]:
        raise HTTPException(status_code=404, detail="no report")
    report = report_from_dict(payload)
    return _attachment(
        render_docx(report),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        _download_name(title, "docx"),
    )


@router.post("/meetings/{meeting_id}/diarize")
def diarize_meeting(meeting_id: int, user: dict = Depends(require_user)) -> dict:
    """Run speaker diarization on existing audio+transcript (no Whisper/summary)."""
    _require_meeting(meeting_id, user)
    try:
        start_diarize(meeting_id)
    except Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": meeting_id, "status": "diarizing"}


@router.post("/meetings/{meeting_id}/chunks")
async def upload_chunk(
    meeting_id: int, request: Request, user: dict = Depends(require_user)
) -> dict:
    _require_meeting(meeting_id, user)
    data = await request.body()
    db.append_audio_chunk(meeting_id, data)
    return {"bytes_written": len(data)}


@router.post("/meetings/{meeting_id}/audio")
async def upload_audio(
    meeting_id: int,
    file: UploadFile = File(...),
    user: dict = Depends(require_user),
) -> dict:
    meeting = _require_meeting(meeting_id, user)
    if meeting["status"] not in ("recording", "error"):
        raise HTTPException(
            status_code=409, detail="meeting is not accepting audio"
        )

    first = await file.read(min(_READ_CHUNK, MAX_AUDIO_BYTES + 1))
    if not first:
        raise HTTPException(status_code=400, detail="empty file")

    ext = guess_audio_ext(file.filename or "", file.content_type or "", first)
    if ext is None:
        raise HTTPException(status_code=400, detail="unsupported media type")

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
def stop_meeting(meeting_id: int, user: dict = Depends(require_user)) -> dict:
    _require_meeting(meeting_id, user)
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
def meeting_status(meeting_id: int, user: dict = Depends(require_user)) -> dict:
    meeting = _require_meeting(meeting_id, user)
    return {
        "status": meeting["status"],
        "error": meeting["error"],
        "counts": db.count_item_statuses(meeting_id),
        "progress": _progress_payload(meeting),
    }


@router.post("/meetings/{meeting_id}/resummarize")
def resummarize_meeting(meeting_id: int, user: dict = Depends(require_user)) -> dict:
    """Пересобрать саммари из уже готового транскрипта (без повторного Whisper)."""
    _require_meeting(meeting_id, user)
    try:
        start_resummarize(meeting_id)
    except Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.set_meeting_status(meeting_id, "processing")
    meeting = db.get_meeting(meeting_id)
    assert meeting is not None
    return {"id": meeting["id"], "status": meeting["status"]}


@router.patch("/meetings/{meeting_id}/items/{item_id}")
def patch_item(
    meeting_id: int,
    item_id: int,
    body: PatchItemBody,
    user: dict = Depends(require_user),
) -> dict:
    _require_meeting(meeting_id, user)
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
def delete_meeting_item(
    meeting_id: int, item_id: int, user: dict = Depends(require_user)
) -> dict:
    _require_meeting(meeting_id, user)
    _require_item(meeting_id, item_id)
    deleted_meeting = db.delete_item(item_id)
    if deleted_meeting is None:
        raise HTTPException(status_code=404, detail="item not found")
    db.maybe_mark_consensus(meeting_id)
    return {"ok": True, "id": item_id}


@router.post("/meetings/{meeting_id}/items/{item_id}/rewrite")
def rewrite_meeting_item(
    meeting_id: int,
    item_id: int,
    body: RewriteBody,
    user: dict = Depends(require_user),
) -> dict:
    _require_meeting(meeting_id, user)
    item = _require_item(meeting_id, item_id)
    new_text = rewrite_item(item["text"], body.objection)
    updated = db.update_item_text(item_id, new_text)
    db.maybe_mark_consensus(meeting_id)
    return updated


@router.post("/meetings/{meeting_id}/items/{item_id}/elaborate")
def elaborate_meeting_item(
    meeting_id: int, item_id: int, user: dict = Depends(require_user)
) -> dict:
    """Предложить уточнённый текст пункта по транскрипту (без записи в БД)."""
    _require_meeting(meeting_id, user)
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