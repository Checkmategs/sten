from sten.transcribe import Segment


def chunk_segments(segments: list[Segment], max_chars: int = 6000) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for s in segments:
        added = len(s.text) if not current else len(s.text) + 1
        if current and current_len + added > max_chars:
            chunks.append("\n".join(current))
            current, current_len = [], 0
            added = len(s.text)
        current.append(s.text)
        current_len += added
    if current:
        chunks.append("\n".join(current))
    return chunks
