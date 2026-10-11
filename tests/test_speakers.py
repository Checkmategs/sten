import json
from pathlib import Path

import pytest

from sten.speakers import SPEAKER_IN_USE, SpeakerInUse, delete_speaker, rename_speaker
from sten.transcribe import Segment
from sten.speakers import save_segments, write_registry


def _meeting(tmp_path: Path) -> Path:
    out = tmp_path / "m"
    save_segments(
        out,
        [
            Segment(0.0, 1.0, "Привет", "Спикер 1"),
            Segment(1.0, 2.0, "Пока", "Спикер 2"),
        ],
    )
    write_registry(out, ["Спикер 1", "Спикер 2"])
    (out / "summary.json").write_text(
        json.dumps(
            {
                "items": [],
                "report": {
                    "title": "Тема",
                    "summary": "",
                    "outcome": "",
                    "participants": [
                        {"speaker": "Спикер 1", "role": "", "name": ""}
                    ],
                    "topics": [],
                    "decisions": [{"text": "Начать", "initiator": "Спикер 1"}],
                    "tasks": [{"text": "Сделать", "assignee": "Спикер 1", "due": ""}],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return out


def test_rename_replaces_every_turn_and_report_labels(tmp_path: Path):
    out = _meeting(tmp_path)
    rows = rename_speaker(out, "Спикер 1", "Сергей")
    assert {row["name"]: row["count"] for row in rows} == {"Сергей": 1, "Спикер 2": 1}
    text = (out / "transcript.txt").read_text(encoding="utf-8")
    assert "Сергей: Привет" in text
    assert "Спикер 1" not in text
    report = json.loads((out / "summary.json").read_text(encoding="utf-8"))["report"]
    assert report["participants"][0]["speaker"] == "Сергей"
    assert report["decisions"][0]["initiator"] == "Сергей"
    assert report["tasks"][0]["assignee"] == "Сергей"


def test_merge_keeps_unused_speaker_until_delete(tmp_path: Path):
    out = _meeting(tmp_path)
    rows = rename_speaker(out, "Спикер 1", "Спикер 2")
    counts = {row["name"]: row["count"] for row in rows}
    assert counts["Спикер 2"] == 2
    assert counts["Спикер 1"] == 0
    with pytest.raises(SpeakerInUse, match="Сначала замените"):
        delete_speaker(out, "Спикер 2")
    left = delete_speaker(out, "Спикер 1")
    assert [row["name"] for row in left] == ["Спикер 2"]
    assert SPEAKER_IN_USE.startswith("Этот спикер ещё используется")
