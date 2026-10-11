import subprocess
import wave
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sten.audio import guess_audio_ext, to_wav16k


def test_guess_audio_ext_telemost_webm_and_other_video():
    ebml = b"\x1a\x45\xdf\xa3" + b"\x00" * 16
    assert guess_audio_ext("telemost.webm", "video/webm", ebml) == "webm"
    assert guess_audio_ext("clip.mkv", "video/x-matroska", ebml) == "mkv"
    assert guess_audio_ext("clip.mov", "video/quicktime", b"") == "mov"
    assert guess_audio_ext("blob", "video/webm", ebml) == "webm"
    assert guess_audio_ext("clip.avi", "application/octet-stream", b"") == "avi"


def test_guess_audio_ext_sniffs_video_containers():
    mov = b"\x00\x00\x00\x14ftypqt  "
    avi = b"RIFF" + b"\x00\x00\x00\x00" + b"AVI "
    assert guess_audio_ext("download", "application/octet-stream", mov) == "mov"
    assert guess_audio_ext("download", "", avi) == "avi"
    assert guess_audio_ext("download", "", b"\x1a\x45\xdf\xa3rest") == "webm"


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
def test_to_wav16k_extracts_audio_from_video(tmp_path: Path):
    src = tmp_path / "telemost.webm"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-f", "lavfi", "-i", "color=c=black:s=160x120:d=1",
            "-c:v", "libvpx", "-c:a", "libopus",
            "-shortest", str(src),
        ],
        check=True, capture_output=True,
    )
    dst = tmp_path / "out.wav"
    result = to_wav16k(src, dst)
    assert result == dst
    with wave.open(str(dst)) as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1
        assert w.getnframes() > 0


@pytest.mark.integration
def test_to_wav16k_raises_on_bad_input(tmp_path: Path):
    src = tmp_path / "garbage.m4a"
    src.write_bytes(b"not audio at all")
    with pytest.raises(RuntimeError):
        to_wav16k(src, tmp_path / "out.wav")
