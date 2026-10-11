import subprocess
from pathlib import Path

import pytest

from sten.transcribe import (
    Segment,
    is_cuda_oom,
    transcript_text,
    transcript_with_time_markers,
    whisper_device_plan,
)


def test_transcript_text_joins_segments():
    segs = [Segment(0.0, 1.0, "Привет."), Segment(1.0, 2.0, "Как дела?")]
    assert transcript_text(segs) == "Привет.\nКак дела?"


def test_transcript_text_empty():
    assert transcript_text([]) == ""


def test_transcript_with_time_markers_every_five_minutes():
    segs = [
        Segment(0.0, 2.0, "Старт"),
        Segment(299.0, 304.0, "Перед отметкой"),
        Segment(301.0, 310.0, "После пяти минут"),
        Segment(600.0, 605.0, "Десять минут"),
        Segment(3720.0, 3725.0, "Час и две минуты"),
    ]
    text = transcript_with_time_markers(segs)
    assert text == (
        "[00:00]\n"
        "Старт\n"
        "Перед отметкой\n"
        "[05:00]\n"
        "После пяти минут\n"
        "[10:00]\n"
        "Десять минут\n"
        "[1:00:00]\n"
        "Час и две минуты"
    )


def test_transcript_with_time_markers_keeps_speakers():
    segs = [
        Segment(0.0, 1.0, "Привет", "Спикер 1"),
        Segment(1.0, 2.0, "всем", "Спикер 1"),
        Segment(2.0, 3.0, "Пока", "Спикер 2"),
        Segment(300.0, 305.0, "Дальше", "Спикер 1"),
    ]
    assert transcript_with_time_markers(segs) == (
        "[00:00]\n"
        "Спикер 1: Привет всем\n"
        "\n"
        "Спикер 2: Пока\n"
        "\n"
        "[05:00]\n"
        "Спикер 1: Дальше"
    )


def test_transcript_with_time_markers_empty():
    assert transcript_with_time_markers([]) == ""


def test_is_cuda_oom():
    assert is_cuda_oom(RuntimeError("CUDA failed with error out of memory"))
    assert not is_cuda_oom(RuntimeError("unsupported compute type"))


def test_whisper_device_plan_uses_freest_gpu_then_lighter_and_cpu():
    plan = whisper_device_plan("float16", gpus=[(0, 4000), (1, 9000), (2, 9000)])
    assert plan == [
        ("cuda", 1, "float16", 2),
        ("cuda", 1, "int8_float16", 8),
        ("cuda", 1, "int8", 8),
        ("cpu", None, "int8", 8),
    ]


def test_whisper_device_plan_shrinks_batch_when_gpu_is_tight():
    plan = whisper_device_plan("float16", gpus=[(0, 5000), (1, 3000)])
    assert plan[0] == ("cuda", 0, "int8", 2)
    assert all(item[2] != "float16" for item in plan if item[0] == "cuda")
    assert plan[-1] == ("cpu", None, "int8", 8)


def test_whisper_device_plan_keeps_float16_batch_when_gpu_is_free():
    plan = whisper_device_plan("float16", gpus=[(0, 16000)])
    assert plan[0] == ("cuda", 0, "float16", 8)


def test_whisper_device_plan_without_gpu_keeps_auto_then_cpu():
    assert whisper_device_plan("float16", gpus=[]) == [
        ("auto", None, "float16", 8),
        ("cpu", None, "int8", 8),
    ]


def test_transcribe_retries_lighter_compute_after_cuda_oom(tmp_path, monkeypatch):
    from sten import transcribe as transcribe_mod

    wav = tmp_path / "speech.wav"
    wav.write_bytes(b"")
    loads: list[str] = []

    class _Seg:
        def __init__(self, text: str):
            self.start = 0.0
            self.end = 1.0
            self.text = text

    class _Model:
        def __init__(self, compute_type: str):
            self.compute_type = compute_type

        def transcribe(self, *_args, **_kwargs):
            if self.compute_type == "float16":
                raise RuntimeError("CUDA failed with error out of memory")
            info = type("Info", (), {"duration": 1.0})()
            return iter([_Seg("Привет")]), info

    def load(_name, _device, _index, compute_type):
        loads.append(compute_type)
        return _Model(compute_type)

    monkeypatch.setattr(
        transcribe_mod,
        "whisper_device_plan",
        lambda _compute, gpus=None: [
            ("cuda", 1, "float16"),
            ("cuda", 1, "int8_float16"),
        ],
    )
    monkeypatch.setattr(transcribe_mod, "_load_whisper", load)
    monkeypatch.setattr(transcribe_mod, "_make_transcriber", lambda model: model)

    segments = transcribe_mod.transcribe(wav)
    assert loads == ["float16", "int8_float16"]
    assert transcript_text(segments) == "Привет"


def test_transcribe_reraises_non_oom(tmp_path, monkeypatch):
    from sten import transcribe as transcribe_mod

    wav = tmp_path / "speech.wav"
    wav.write_bytes(b"")

    def load(*_args):
        raise RuntimeError("model files missing")

    monkeypatch.setattr(
        transcribe_mod, "whisper_device_plan", lambda _compute, gpus=None: [("cuda", 0, "float16")]
    )
    monkeypatch.setattr(transcribe_mod, "_load_whisper", load)
    monkeypatch.setattr(transcribe_mod, "_make_transcriber", lambda model: model)

    with pytest.raises(RuntimeError, match="model files missing"):
        transcribe_mod.transcribe(wav)


@pytest.mark.integration
def test_transcribe_russian_speech(tmp_path: Path):
    from sten.audio import to_wav16k
    from sten.transcribe import transcribe

    voices = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    if "Milena" not in voices:
        pytest.skip("Russian voice Milena not installed")

    aiff = tmp_path / "speech.aiff"
    subprocess.run(
        ["say", "-v", "Milena", "-o", str(aiff),
         "Мы решили запустить проект в сентябре."],
        check=True,
    )
    wav = to_wav16k(aiff, tmp_path / "speech.wav")
    segments = transcribe(wav)
    text = transcript_text(segments).lower()
    assert "сентябре" in text or "сентябрь" in text
