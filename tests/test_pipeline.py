import json
from pathlib import Path

from sten.items import SummaryItem
from sten.pipeline import overall_percent, render_markdown, run, write_outputs
from sten.transcribe import Segment


def test_overall_percent_maps_stages():
    assert overall_percent(1, 0.0) == 0
    assert overall_percent(1, 1.0) == 8
    assert overall_percent(2, 0.0) == 8
    assert overall_percent(2, 0.5) == 34
    assert overall_percent(2, 1.0) == 60
    assert overall_percent(3, 0.0) == 60
    assert overall_percent(3, 1.0) == 82
    assert overall_percent(4, 0.0) == 82
    assert overall_percent(4, 1.0) == 99


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
    labeled = [Segment(0.0, 1.0, "Привет", speaker="Спикер 1")]
    seen: dict = {}

    monkeypatch.setattr("sten.pipeline.to_wav16k", lambda src, dest: wav)
    monkeypatch.setattr(
        "sten.pipeline.transcribe", lambda wav_path, on_progress=None: plain
    )

    def fake_diarize(segs, wav_path):
        seen["wav"] = wav_path
        return labeled

    monkeypatch.setattr("sten.diarize.diarize_segments", fake_diarize)

    out = tmp_path / "out"
    run(audio, out)

    assert seen["wav"] == wav
    assert "Спикер 1: Привет" in (out / "transcript.txt").read_text(encoding="utf-8")
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["items"] == []
    assert not (out / "diarize_error.txt").exists()


def test_run_keeps_transcript_when_diarization_fails(tmp_path: Path, monkeypatch):
    audio = tmp_path / "in.webm"
    audio.write_bytes(b"x")
    plain = [Segment(0.0, 1.0, "Привет")]

    monkeypatch.setattr("sten.pipeline.to_wav16k", lambda src, dest: tmp_path / "audio.wav")
    monkeypatch.setattr(
        "sten.pipeline.transcribe", lambda wav_path, on_progress=None: plain
    )

    def fail_diarize(segs, wav_path):
        raise RuntimeError("нет модели")

    monkeypatch.setattr("sten.diarize.diarize_segments", fail_diarize)

    out = tmp_path / "out"
    run(audio, out)

    assert (out / "transcript.txt").read_text(encoding="utf-8") == "Привет"
    assert "нет модели" in (out / "diarize_error.txt").read_text(encoding="utf-8")
