"""Unit tests for empty-transcript / empty-summary handling in processing."""

import json
from pathlib import Path

import pytest

from pathlib import Path

import pytest

from sten import db
from sten.api import processing


def _write_out(
    out_dir: Path, *, transcript: str, items: list, report: dict | None = None
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "transcript.txt").write_text(transcript, encoding="utf-8")
    summary: dict = {"items": items}
    if report is not None:
        summary["report"] = report
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False), encoding="utf-8"
    )


def test_load_items_rejects_empty_transcript(tmp_path: Path):
    out = tmp_path / "m"
    _write_out(out, transcript="", items=[])
    with pytest.raises(RuntimeError, match="не распознана речь"):
        processing.load_items_from_output(out)


def test_load_items_allows_empty_summary(tmp_path: Path):
    out = tmp_path / "m"
    _write_out(out, transcript="Что-то сказали", items=[])
    assert processing.load_items_from_output(out) == []


def test_load_items_ok(tmp_path: Path):
    out = tmp_path / "m"
    _write_out(
        out,
        transcript="Решили X",
        items=[{"text": "Решили X", "category": "decision", "theme": "Релиз"}],
    )
    assert processing.load_items_from_output(out) == [
        ("Решили X", "decision", "Релиз")
    ]


def test_process_meeting_uses_uploaded_m4a(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "sten.db")
    monkeypatch.setattr(db, "DATA_DIR", tmp_path / "data")
    db.init_db()
    mid = db.create_meeting("A")
    audio = db.save_uploaded_audio(mid, "m4a")
    audio.write_bytes(b"fake")

    called: list[Path] = []

    def fake_run(audio_path, out_dir, on_stage=None):
        called.append(audio_path)
        if on_stage:
            on_stage(1, 3, "Конвертация аудио…")
        _write_out(
            out_dir,
            transcript="Речь",
            items=[{"text": "Пункт", "category": "topic", "theme": "Общее"}],
        )

    monkeypatch.setattr(processing.pipeline, "run", fake_run)
    processing._process_meeting(mid)
    assert called == [audio]
    assert db.get_meeting(mid)["status"] == "ready"


def test_process_meeting_adopts_brief_title(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "sten.db")
    monkeypatch.setattr(db, "DATA_DIR", tmp_path / "data")
    db.init_db()
    mid = db.create_meeting("Встреча 2026-10-12 00:09")
    audio = db.save_uploaded_audio(mid, "m4a")
    audio.write_bytes(b"fake")

    def fake_run(audio_path, out_dir, on_stage=None):
        _write_out(
            out_dir,
            transcript="Речь",
            items=[],
            report={"title": "Планёрка по релизу"},
        )

    monkeypatch.setattr(processing.pipeline, "run", fake_run)
    processing._process_meeting(mid)
    assert db.get_meeting(mid)["title"] == "Планёрка по релизу"


def test_adopt_brief_title_keeps_custom_name(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "sten.db")
    monkeypatch.setattr(db, "DATA_DIR", tmp_path / "data")
    db.init_db()
    mid = db.create_meeting("Своё название")
    out = tmp_path / "data" / "meetings" / str(mid)
    _write_out(out, transcript="Речь", items=[], report={"title": "Из обзора"})
    meeting = db.get_meeting(mid)
    assert meeting is not None
    assert processing.adopt_brief_title(meeting) == "Своё название"
    assert db.get_meeting(mid)["title"] == "Своё название"
