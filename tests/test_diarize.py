from sten.diarize import Turn, assign_speakers, merge_turns, speaker_display_names
from sten.transcribe import Segment, transcript_text


def test_speaker_display_names_by_appearance():
    assert speaker_display_names(["SPEAKER_01", "SPEAKER_00", "SPEAKER_01"]) == {
        "SPEAKER_01": "Спикер 1",
        "SPEAKER_00": "Спикер 2",
    }


def test_assign_speakers_by_overlap():
    segs = [
        Segment(0.0, 5.0, "Привет"),
        Segment(5.0, 10.0, "Как дела"),
        Segment(10.0, 15.0, "Хорошо"),
    ]
    diar = [
        (0.0, 6.0, "SPEAKER_00"),
        (6.0, 20.0, "SPEAKER_01"),
    ]
    out = assign_speakers(segs, diar)
    assert [s.speaker for s in out] == ["Спикер 1", "Спикер 2", "Спикер 2"]


def test_assign_speakers_empty_diarization():
    segs = [Segment(0.0, 1.0, "A")]
    assert assign_speakers(segs, [])[0].speaker is None


def test_merge_turns_consecutive_same_speaker():
    segs = [
        Segment(0.0, 1.0, "Раз", speaker="Спикер 1"),
        Segment(1.0, 2.0, "два", speaker="Спикер 1"),
        Segment(2.0, 3.0, "Три", speaker="Спикер 2"),
    ]
    turns = merge_turns(segs)
    assert turns == [
        Turn(speaker="Спикер 1", start=0.0, end=2.0, text="Раз два"),
        Turn(speaker="Спикер 2", start=2.0, end=3.0, text="Три"),
    ]


def test_transcript_text_with_speakers():
    segs = [
        Segment(0.0, 1.0, "Привет", speaker="Спикер 1"),
        Segment(1.0, 2.0, "Пока", speaker="Спикер 2"),
    ]
    assert transcript_text(segs) == "Спикер 1: Привет\n\nСпикер 2: Пока"


def test_transcript_text_without_speakers_unchanged():
    segs = [Segment(0.0, 1.0, "Привет."), Segment(1.0, 2.0, "Как дела?")]
    assert transcript_text(segs) == "Привет.\nКак дела?"
