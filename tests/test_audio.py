import subprocess
import wave
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sten.audio import to_wav16k


def test_to_wav16k_same_path_writes_via_temp(tmp_path: Path, monkeypatch):
    src = tmp_path / "audio.wav"
    src.write_bytes(b"RIFF-old")

    def fake_run(args, **_kwargs):
        dest = Path(args[-1])
        assert dest != src
        dest.write_bytes(b"WAV-new")
        return MagicMock(returncode=0, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = to_wav16k(src, src)
    assert result == src
    assert src.read_bytes() == b"WAV-new"
    assert list(tmp_path.glob("*.tmp.wav")) == []


@pytest.mark.integration
def test_to_wav16k_converts_to_16k_mono(tmp_path: Path):
    src = tmp_path / "tone.m4a"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-ar", "44100", "-ac", "2", str(src)],
        check=True, capture_output=True,
    )
    dst = tmp_path / "out.wav"
    result = to_wav16k(src, dst)
    assert result == dst
    with wave.open(str(dst)) as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1


@pytest.mark.integration
def test_to_wav16k_raises_on_bad_input(tmp_path: Path):
    src = tmp_path / "garbage.m4a"
    src.write_bytes(b"not audio at all")
    with pytest.raises(RuntimeError):
        to_wav16k(src, tmp_path / "out.wav")
