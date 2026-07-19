from sten.chunking import chunk_segments
from sten.transcribe import Segment


def seg(text: str) -> Segment:
    return Segment(0.0, 1.0, text)


def test_empty_input():
    assert chunk_segments([]) == []


def test_all_fits_in_one_chunk():
    segs = [seg("Раз."), seg("Два.")]
    assert chunk_segments(segs, max_chars=100) == ["Раз.\nДва."]


def test_splits_on_segment_boundary():
    segs = [seg("а" * 40), seg("б" * 40), seg("в" * 40)]
    chunks = chunk_segments(segs, max_chars=90)
    assert chunks == ["а" * 40 + "\n" + "б" * 40, "в" * 40]
    assert all(len(c) <= 90 for c in chunks)


def test_oversized_single_segment_kept_whole():
    segs = [seg("х" * 200)]
    assert chunk_segments(segs, max_chars=100) == ["х" * 200]
