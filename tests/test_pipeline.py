import json
from pathlib import Path

import pytest

from sten.items import SummaryItem
from sten.report import MeetingReport
from sten.pipeline import (
    diarize_creep,
    overall_percent,
    pipeline_devices,
    render_markdown,
    run,
    write_outputs,
)
from sten.transcribe import Segment


@pytest.fixture(autouse=True)
def _stub_meeting_report(monkeypatch):
    from sten.dialogue import DialogueMap

    def fake(segments, on_progress=None):
        if on_progress is not None:
            on_progress(1.0)
        return MeetingReport()

    def fake_dialogue(segments, on_progress=None):
        if on_progress is not None:
            on_progress(1.0)
        return DialogueMap()

    monkeypatch.setattr("sten.pipeline.build_report", fake)
    monkeypatch.setattr("sten.pipeline.build_dialogue", fake_dialogue)


def test_overall_percent_maps_stages():
    assert overall_percent(1, 0.0) == 0
    assert overall_percent(1, 1.0) == 5
    assert overall_percent(2, 0.0) == 5
    assert overall_percent(2, 0.5) == 22
    assert overall_percent(2, 1.0) == 38
    assert overall_percent(3, 0.0) == 38
    assert overall_percent(3, 1.0) == 70
    assert overall_percent(4, 0.0) == 70
    assert overall_percent(4, 1.0) == 99


def test_pipeline_devices_splits_two_gpus_and_keeps_one_sequential():
    assert pipeline_devices([(1, 9000), (0, 4000)]) == ([(1, 9000)], 0)
    assert pipeline_devices([(0, 8000)]) == (None, None)
    assert pipeline_devices([]) == (None, None)


def test_run_keeps_diarize_bar_moving(tmp_path: Path, monkeypatch):
    import time

    audio = tmp_path / "in.webm"
    audio.write_bytes(b"x")
    plain = [Segment(0.0, 1.0, "Привет")]
    monkeypatch.setattr("sten.pipeline.to_wav16k", lambda src, dest: tmp_path / "audio.wav")
    monkeypatch.setattr(
        "sten.pipeline.transcribe", lambda wav_path, on_progress=None, **_kwargs: plain
    )

    def slow_diarize(wav_path, device_index=None):
        time.sleep(1.3)
        return []

    monkeypatch.setattr("sten.diarize.diarize_wav", slow_diarize)
    seen: list[tuple[int, str, int]] = []

    def on_stage(step: int, total: int, label: str, pct: int) -> None:
        seen.append((step, label, pct))

    run(audio, tmp_path / "out", on_stage=on_stage)

    diar = [row for row in seen if row[0] == 3]
    assert diar[0] == (3, "Идёт разметка спикеров…", 38)
    assert any(38 < pct < 70 for _, _, pct in diar)
    assert diar[-1] == (3, "Идёт разметка спикеров…", 70)
    report = [row for row in seen if row[0] == 4]
    assert report[0][2] == 70
    assert report[-1][2] == 99
    assert all(report[i][2] <= report[i + 1][2] for i in range(len(report) - 1))


def test_run_keeps_report_bar_moving(tmp_path: Path, monkeypatch):
    import time

    audio = tmp_path / "in.webm"
    audio.write_bytes(b"x")
    plain = [Segment(0.0, 1.0, "Привет")]
    monkeypatch.setattr("sten.pipeline.to_wav16k", lambda src, dest: tmp_path / "audio.wav")
    monkeypatch.setattr(
        "sten.pipeline.transcribe", lambda wav_path, on_progress=None, **_kwargs: plain
    )
    monkeypatch.setattr("sten.diarize.diarize_wav", lambda wav_path, device_index=None: [])

    def slow_report(segments, on_progress=None):
        time.sleep(1.4)
        if on_progress is not None:
            on_progress(1.0)
        return MeetingReport()

    monkeypatch.setattr("sten.pipeline.build_report", slow_report)
    seen: list[int] = []

    def on_stage(step: int, total: int, label: str, pct: int) -> None:
        if step == 4:
            seen.append(pct)

    run(audio, tmp_path / "out", on_stage=on_stage)

    assert seen[0] == 70
    assert any(70 < pct < 99 for pct in seen)
    assert seen[-1] == 99
    assert all(seen[i] <= seen[i + 1] for i in range(len(seen) - 1))


def test_diarize_creep_advances_then_holds_short_of_done():
    assert diarize_creep(0, 100) == 0
    assert 0.6 < diarize_creep(100, 100) < 0.7
    assert diarize_creep(10_000, 100) == 0.92
    assert diarize_creep(50, 100) < diarize_creep(100, 100)


def test_render_markdown_groups_by_theme():
    items = [
        SummaryItem("Запуск в сентябре", "decision", "Релиз"),
        SummaryItem("Иван готовит план к пятнице", "task", "Релиз"),
        SummaryItem("Бюджет не согласован", "question", "Бюджет"),
    ]
    md = render_markdown(items)
    assert md.index("## Релиз") < md.index("## Бюджет")
    assert "**Решение:** Запуск в сентябре" in md
    assert "**Задача:** Иван готовит план к пятнице" in md
    assert "**Открытый вопрос:** Бюджет не согласован" in md


def test_render_markdown_empty():
    assert "нет пунктов" in render_markdown([]).lower()


def test_write_outputs_creates_all_files(tmp_path: Path):
    segments = [Segment(0.0, 1.5, "Привет всем.")]
    items = [SummaryItem("Поздоровались", "topic", "Старт")]
    write_outputs(tmp_path, segments, items)

    assert (tmp_path / "transcript.txt").read_text(encoding="utf-8") == "Привет всем."
    tj = json.loads((tmp_path / "transcript.json").read_text(encoding="utf-8"))
    assert tj == [
        {"start": 0.0, "end": 1.5, "text": "Привет всем.", "speaker": None}
    ]
    sj = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert sj == {
        "items": [
            {"text": "Поздоровались", "category": "topic", "theme": "Старт"}
        ]
    }
    assert "Поздоровались" in (tmp_path / "summary.md").read_text(encoding="utf-8")


def test_run_labels_speakers_before_summary(tmp_path: Path, monkeypatch):
    audio = tmp_path / "in.webm"
    audio.write_bytes(b"x")
    wav = tmp_path / "audio.wav"
    plain = [Segment(0.0, 1.0, "Привет")]
    seen: dict = {}

    monkeypatch.setattr("sten.pipeline.to_wav16k", lambda src, dest: wav)
    monkeypatch.setattr(
        "sten.pipeline.gpu_memory_free_mib",
        lambda: [(1, 9000), (2, 8000)],
    )

    def fake_transcribe(wav_path, on_progress=None, gpus=None):
        seen["gpus"] = gpus
        return plain

    monkeypatch.setattr("sten.pipeline.transcribe", fake_transcribe)

    def fake_diarize(wav_path, device_index=None):
        seen["wav"] = wav_path
        seen["device"] = device_index
        return [(0.0, 1.0, "SPEAKER_00")]

    monkeypatch.setattr("sten.diarize.diarize_wav", fake_diarize)

    out = tmp_path / "out"
    run(audio, out)

    assert seen["wav"] == wav
    assert seen["gpus"] == [(1, 9000)]
    assert seen["device"] == 2
    assert "Спикер 1: Привет" in (out / "transcript.txt").read_text(encoding="utf-8")
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["items"] == []
    assert summary["report"]["title"] == ""
    speakers = json.loads((out / "speakers.json").read_text(encoding="utf-8"))
    assert speakers["speakers"] == ["Спикер 1"]
    assert not (out / "diarize_error.txt").exists()


def test_run_keeps_transcript_when_diarization_fails(tmp_path: Path, monkeypatch):
    audio = tmp_path / "in.webm"
    audio.write_bytes(b"x")
    plain = [Segment(0.0, 1.0, "Привет")]

    monkeypatch.setattr("sten.pipeline.to_wav16k", lambda src, dest: tmp_path / "audio.wav")
    monkeypatch.setattr(
        "sten.pipeline.transcribe", lambda wav_path, on_progress=None, **_kwargs: plain
    )

    def fail_diarize(wav_path, device_index=None):
        raise RuntimeError("нет модели")

    monkeypatch.setattr("sten.diarize.diarize_wav", fail_diarize)

    out = tmp_path / "out"
    run(audio, out)

    assert (out / "transcript.txt").read_text(encoding="utf-8") == "Привет"
    assert "нет модели" in (out / "diarize_error.txt").read_text(encoding="utf-8")
