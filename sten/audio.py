import subprocess
from pathlib import Path

from sten.db import ALLOWED_AUDIO_EXTS

_MIME_TO_EXT = {
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
    "audio/m4b": "m4a",
    "audio/x-caf": "caf",
    "audio/caf": "caf",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/wave": "wav",
    "audio/x-wav": "wav",
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "application/ogg": "ogg",
    "audio/oga": "ogg",
    "audio/aac": "aac",
    "audio/x-aac": "aac",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/x-matroska": "mkv",
    "video/quicktime": "mov",
    "video/x-msvideo": "avi",
    "video/avi": "avi",
    "video/mpeg": "mpeg",
    "video/x-m4v": "m4v",
    "video/3gpp": "3gp",
    "video/3gpp2": "3gp",
    "video/x-ms-wmv": "wmv",
    "video/x-flv": "flv",
}


def guess_audio_ext(filename: str, content_type: str, header: bytes) -> str | None:
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix in ALLOWED_AUDIO_EXTS:
        return suffix
    mime = (content_type or "").split(";")[0].strip().lower()
    mapped = _MIME_TO_EXT.get(mime)
    if mapped:
        return mapped
    sniffed = _sniff_audio_ext(header)
    if sniffed in ALLOWED_AUDIO_EXTS:
        return sniffed
    return None


def _sniff_audio_ext(header: bytes) -> str | None:
    if len(header) >= 12 and header[4:8] == b"ftyp":
        brand = header[8:12]
        if brand == b"qt  ":
            return "mov"
        if brand in {b"M4V ", b"m4v "}:
            return "m4v"
        if brand in {b"M4A ", b"M4B "}:
            return "m4a"
        return "mp4"
    if header.startswith(b"RIFF") and len(header) >= 12:
        kind = header[8:12]
        if kind == b"WAVE":
            return "wav"
        if kind == b"AVI ":
            return "avi"
    if header.startswith(b"OggS"):
        return "ogg"
    if header.startswith(b"fLaC"):
        return "flac"
    if header.startswith(b"caff"):
        return "caf"
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    if header.startswith(b"FLV"):
        return "flv"
    if header.startswith(b"ID3") or header[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "mp3"
    return None


def to_wav16k(src: Path, dst: Path) -> Path:
    src = src.resolve()
    dst = dst.resolve()
    write_to = dst
    if src == dst:
        write_to = dst.with_name(dst.stem + ".convert.tmp.wav")
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-i", str(src),
                "-vn", "-map", "0:a:0",
                "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(write_to),
            ],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=1800,
        )
    except subprocess.TimeoutExpired as exc:
        if write_to != dst and write_to.exists():
            write_to.unlink(missing_ok=True)
        raise RuntimeError("ffmpeg timed out converting audio") from exc
    if proc.returncode != 0:
        if write_to != dst and write_to.exists():
            write_to.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg failed: {proc.stderr[-500:]}")
    if write_to != dst:
        write_to.replace(dst)
    return dst
