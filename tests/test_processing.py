"""Unit tests for empty-transcript / empty-summary handling in processing."""

import json
from pathlib import Path

import pytest

from sten.api import processing


def _write_out(out_dir: Path, *, transcript: str, items: list) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "transcript.txt").write_text(transcript, encoding="utf-8")
    (out_dir / "summary.json").write_text(
        json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8"
    )


def test_load_items_rejects_empty_transcript(tmp_path: Path):
    out = tmp_path / "m"
    _write_out(out, transcript="", items=[])
    with pytest.raises(RuntimeError, match="не распознана речь"):
        processing.load_items_from_output(out)


def test_load_items_rejects_empty_summary(tmp_path: Path):
    out = tmp_path / "m"
    _write_out(out, transcript="Что-то сказали", items=[])
    with pytest.raises(RuntimeError, match="пункты саммари пустые"):
        processing.load_items_from_output(out)


def test_load_items_ok(tmp_path: Path):
    out = tmp_path / "m"
    _write_out(
        out,
        transcript="Решили X",
        items=[{"text": "Решили X", "category": "decision"}],
    )
    assert processing.load_items_from_output(out) == [("Решили X", "decision")]
