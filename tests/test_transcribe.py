import subprocess
from pathlib import Path

import pytest

from sten.transcribe import Segment, transcript_text


def test_transcript_text_joins_segments():
    segs = [Segment(0.0, 1.0, "Привет."), Segment(1.0, 2.0, "Как дела?")]
    assert transcript_text(segs) == "Привет.\nКак дела?"


def test_transcript_text_empty():
    assert transcript_text([]) == ""


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
