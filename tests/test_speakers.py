import io
import json
from pathlib import Path

import pytest

from sten.speakers import (
    SAMPLE_SECONDS,
    SPEAKER_IN_USE,
    SpeakerInUse,
    delete_speaker,
    merge_speakers,
    rename_speaker,
    render_speaker_sample,
    single_voice_spans,
    speaker_sample_file,
    speaker_voice_spans,
)
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


def test_rename_updates_dialogue_authors(tmp_path: Path):
    out = _meeting(tmp_path)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    summary["dialogue"] = {
        "questions": [
            {
                "text": "Как назвать?",
                "ideas": [
                    {
                        "text": "Коротко",
                        "status": "open",
                        "author": "Спикер 1",
                        "pros": [{"text": "Проще", "author": "Спикер 1"}],
                        "cons": [],
                    }
                ],
            }
        ]
    }
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False), encoding="utf-8"
    )
    rename_speaker(out, "Спикер 1", "Сергей")
    dialogue = json.loads((out / "summary.json").read_text(encoding="utf-8"))["dialogue"]
    idea = dialogue["questions"][0]["ideas"][0]
    assert idea["author"] == "Сергей"
    assert idea["pros"][0]["author"] == "Сергей"


def test_voice_spans_take_the_longest_clean_stretch():
    segments = [
        Segment(0.0, 3.0, "а", "Спикер 1"),
        Segment(3.0, 4.0, "чужой", "Спикер 2"),
        Segment(4.0, 20.0, "б", "Спикер 1"),
    ]
    # The opening is short and sits against another voice. The sample is the
    # middle of the long uninterrupted stretch, not the first ten seconds.
    assert speaker_voice_spans(segments, "Спикер 1") == [(7.0, 17.0)]
    assert SAMPLE_SECONDS == 10.0


def test_voice_span_keeps_a_short_breath_and_skips_a_pause():
    breath = [
        Segment(0.0, 4.0, "а", "Спикер 1"),
        Segment(4.2, 9.0, "б", "Спикер 1"),
    ]
    assert speaker_voice_spans(breath, "Спикер 1") == [(0.0, 9.0)]
    pause = [
        Segment(0.0, 4.0, "а", "Спикер 1"),
        Segment(6.0, 11.0, "б", "Спикер 1"),
    ]
    assert speaker_voice_spans(pause, "Спикер 1") == [(6.0, 11.0)]


def _keep_ranges(monkeypatch) -> None:
    monkeypatch.setattr(
        "sten.speakers.segment_single_voice",
        lambda path, ranges: ranges,
    )


def test_single_voice_spans_stop_at_overlap_and_a_second_person():
    hop = 0.1
    frames: list[list[float]] = []
    frames += [[0.9, 0.05]] * 10
    frames += [[0.8, 0.8]] * 5
    frames += [[0.05, 0.9]] * 20
    assert single_voice_spans(frames, hop, 0.0) == [(0.0, 1.0), (1.5, 3.5)]


def test_sample_wav_is_ten_seconds_of_that_speaker(tmp_path: Path, monkeypatch):
    _keep_ranges(monkeypatch)
    import wave

    out = _meeting(tmp_path)
    save_segments(
        out,
        [
            Segment(0.0, 3.0, "а", "Спикер 1"),
            Segment(3.0, 4.0, "чужой", "Спикер 2"),
            Segment(4.0, 20.0, "б", "Спикер 1"),
        ],
    )
    rate = 16000
    wav_path = out / "audio.wav"
    with wave.open(str(wav_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * (20 * rate))

    payload = render_speaker_sample(out, "Спикер 1")
    with wave.open(io.BytesIO(payload), "rb") as handle:
        assert handle.getnframes() == 10 * rate
        assert handle.getframerate() == rate


def test_sample_uses_clean_speech_not_a_pause_or_other_voice(tmp_path: Path, monkeypatch):
    _keep_ranges(monkeypatch)
    import array
    import wave

    out = _meeting(tmp_path)
    save_segments(
        out,
        [
            Segment(0.0, 20.0, "долго", "Спикер 1"),
            Segment(6.0, 8.0, "чужой", "Спикер 2"),
        ],
    )
    rate = 16000
    samples = array.array("h")
    samples.extend([2000] * (3 * rate))
    samples.extend([0] * (3 * rate))
    samples.extend([9000] * (2 * rate))
    samples.extend([2000] * (12 * rate))
    wav_path = out / "audio.wav"
    with wave.open(str(wav_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())

    payload = render_speaker_sample(out, "Спикер 1")
    with wave.open(io.BytesIO(payload), "rb") as handle:
        assert handle.getnframes() == 10 * rate
        heard = array.array("h")
        heard.frombytes(handle.readframes(handle.getnframes()))
    assert heard
    assert max(abs(sample) for sample in heard) == 2000
    assert all(sample != 9000 and sample != 0 for sample in heard)


def test_sample_is_only_the_single_voice_interval(tmp_path: Path, monkeypatch):
    import array
    import wave

    out = _meeting(tmp_path)
    save_segments(out, [Segment(0.0, 8.0, "смешанное", "Спикер 1")])
    rate = 16000
    samples = array.array("h", [1000] * (2 * rate) + [4000] * (3 * rate) + [1000] * (3 * rate))
    wav_path = out / "audio.wav"
    with wave.open(str(wav_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())
    monkeypatch.setattr(
        "sten.speakers.segment_single_voice",
        lambda path, ranges: [(2.0, 5.0)],
    )

    payload = render_speaker_sample(out, "Спикер 1")
    with wave.open(io.BytesIO(payload), "rb") as handle:
        heard = array.array("h")
        heard.frombytes(handle.readframes(handle.getnframes()))
        duration = handle.getnframes() / handle.getframerate()
    assert duration == pytest.approx(3.0, abs=0.02)
    assert heard
    assert set(heard) == {4000}


def test_loud_spike_does_not_drop_the_longer_quiet_phrase(tmp_path: Path, monkeypatch):
    _keep_ranges(monkeypatch)
    import array
    import wave

    out = _meeting(tmp_path)
    save_segments(
        out,
        [
            Segment(0.0, 3.0, "коротко", "Спикер 1"),
            Segment(5.0, 11.0, "длинно", "Спикер 1"),
        ],
    )
    rate = 16000
    samples = array.array("h", [3000] * (3 * rate))
    samples.extend([0] * (2 * rate))
    samples.extend([800] * (6 * rate))
    spike_at = 8 * rate
    for index in range(spike_at, spike_at + int(0.1 * rate)):
        samples[index] = 20000
    wav_path = out / "audio.wav"
    with wave.open(str(wav_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())

    payload = render_speaker_sample(out, "Спикер 1")
    with wave.open(io.BytesIO(payload), "rb") as handle:
        heard = array.array("h")
        heard.frombytes(handle.readframes(handle.getnframes()))
        duration = handle.getnframes() / handle.getframerate()
    assert duration > 5
    assert heard.count(800) > heard.count(3000)


def test_speaker_sample_mp3_is_reused_until_the_recording_changes(tmp_path: Path, monkeypatch):
    _keep_ranges(monkeypatch)
    import wave

    out = _meeting(tmp_path)
    rate = 8000
    with wave.open(str(out / "audio.wav"), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x01\x00" * (12 * rate))

    path = speaker_sample_file(out, "Спикер 1")
    assert path.suffix == ".mp3"
    original = path.read_bytes()
    assert original[:3] == b"ID3" or original[0] == 0xFF
    path.write_bytes(b"stored-mp3")

    assert speaker_sample_file(out, "Спикер 1").read_bytes() == b"stored-mp3"

    import os

    os.utime(out / "transcript.json", ns=(1_000_000_000, 1_000_000_000))
    fresh = speaker_sample_file(out, "Спикер 1").read_bytes()
    assert fresh != b"stored-mp3"
    assert fresh[:3] == b"ID3" or fresh[0] == 0xFF


def test_merge_speakers_keeps_the_chosen_name(tmp_path: Path):
    out = _meeting(tmp_path)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    summary["report"]["participants"].append(
        {"speaker": "Спикер 2", "role": "ведущий", "name": "Анна"}
    )
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False), encoding="utf-8"
    )

    rows = merge_speakers(out, "Спикер 1", "Спикер 2")
    assert rows == [{"name": "Спикер 2", "count": 2}]
    text = (out / "transcript.txt").read_text(encoding="utf-8")
    assert "Спикер 2: Привет" in text
    assert "Спикер 1" not in text
    report = json.loads((out / "summary.json").read_text(encoding="utf-8"))["report"]
    assert report["participants"] == [
        {"speaker": "Спикер 2", "role": "ведущий", "name": "Анна"}
    ]
    assert report["decisions"][0]["initiator"] == "Спикер 2"
    assert report["tasks"][0]["assignee"] == "Спикер 2"


def test_merge_speakers_renames_participant_when_target_has_none(tmp_path: Path):
    out = _meeting(tmp_path)
    rows = merge_speakers(out, "Спикер 1", "Спикер 2")
    assert [row["name"] for row in rows] == ["Спикер 2"]
    report = json.loads((out / "summary.json").read_text(encoding="utf-8"))["report"]
    assert report["participants"] == [{"speaker": "Спикер 2", "role": "", "name": ""}]


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
