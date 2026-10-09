from pathlib import Path

import pytest

from sten import db


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "sten.db")
    monkeypatch.setattr(db, "DATA_DIR", tmp_path / "data")
    db.init_db()
    return tmp_path


def test_create_and_get_meeting(isolated_db):
    mid = db.create_meeting("Стендап")
    m = db.get_meeting(mid)
    assert m["title"] == "Стендап"
    assert m["status"] == "recording"


def test_delete_meeting_removes_row_items_and_files(isolated_db):
    mid = db.create_meeting("A")
    db.replace_items(mid, [("Пункт", "topic", "Общее")])
    audio = db.append_audio_chunk(mid, b"abc")
    assert audio.is_file()

    assert db.delete_meeting(mid) is True
    assert db.get_meeting(mid) is None
    assert db.list_items(mid) == []
    assert not audio.exists()
    assert db.delete_meeting(mid) is False


def test_append_audio_chunk_creates_file(isolated_db):
    mid = db.create_meeting("A")
    p = db.append_audio_chunk(mid, b"abc")
    p2 = db.append_audio_chunk(mid, b"def")
    assert p == p2
    assert p.read_bytes() == b"abcdef"


def test_replace_and_list_items(isolated_db):
    mid = db.create_meeting("A")
    db.replace_items(mid, [("Решили X", "decision", "Общее"), ("Сделать Y", "task", "Общее")])
    items = db.list_items(mid)
    assert [i["text"] for i in items] == ["Решили X", "Сделать Y"]
    assert all(i["status"] == "pending" for i in items)


def test_accept_item_and_counts(isolated_db):
    mid = db.create_meeting("A")
    db.replace_items(mid, [("A", "topic", "Общее"), ("B", "topic", "Общее")])
    items = db.list_items(mid)
    db.set_item_status(items[0]["id"], "accepted")
    assert db.count_item_statuses(mid) == {"pending": 1, "accepted": 1}


def test_all_accepted_marks_consensus(isolated_db):
    mid = db.create_meeting("A")
    db.replace_items(mid, [("A", "topic", "Общее")])
    item = db.list_items(mid)[0]
    db.set_item_status(item["id"], "accepted")
    # helper used by API later — test it here if implemented in db
    db.maybe_mark_consensus(mid)
    assert db.get_meeting(mid)["status"] == "consensus"


def test_reopen_item_returns_meeting_to_ready(isolated_db):
    mid = db.create_meeting("A")
    db.replace_items(mid, [("A", "topic", "Общее")])
    item = db.list_items(mid)[0]
    db.set_item_status(item["id"], "accepted")
    db.maybe_mark_consensus(mid)
    assert db.get_meeting(mid)["status"] == "consensus"

    db.set_item_status(item["id"], "pending")
    assert db.get_meeting(mid)["status"] == "ready"


def test_delete_item(isolated_db):
    mid = db.create_meeting("A")
    db.replace_items(mid, [("A", "topic", "Общее"), ("B", "topic", "Общее")])
    items = db.list_items(mid)
    assert db.delete_item(items[0]["id"]) == mid
    assert [i["text"] for i in db.list_items(mid)] == ["B"]
    assert db.delete_item(99999) is None


def test_delete_last_pending_marks_consensus(isolated_db):
    mid = db.create_meeting("A")
    db.replace_items(mid, [("A", "topic", "Общее"), ("B", "topic", "Общее")])
    items = db.list_items(mid)
    db.set_item_status(items[0]["id"], "accepted")
    db.delete_item(items[1]["id"])
    db.maybe_mark_consensus(mid)
    assert db.get_meeting(mid)["status"] == "consensus"


def test_save_uploaded_audio_uses_extension(isolated_db):
    mid = db.create_meeting("A")
    path = db.save_uploaded_audio(mid, "m4a")
    assert path.name == "audio.m4a"
    assert path.parent.exists()
    path.write_bytes(b"data")
    assert path.read_bytes() == b"data"


def test_find_source_audio_prefers_webm_over_m4a(isolated_db):
    mid = db.create_meeting("A")
    m4a = db.save_uploaded_audio(mid, "m4a")
    m4a.write_bytes(b"m4a")
    assert db.find_source_audio(mid) == m4a

    webm = db.append_audio_chunk(mid, b"webm")
    assert db.find_source_audio(mid) == webm


def test_find_source_audio_wav_is_last_resort(isolated_db):
    mid = db.create_meeting("A")
    out = isolated_db / "data" / "meetings" / str(mid)
    out.mkdir(parents=True)
    wav = out / "audio.wav"
    wav.write_bytes(b"RIFF")
    assert db.find_source_audio(mid) == wav

    m4a = out / "audio.m4a"
    m4a.write_bytes(b"m4a")
    assert db.find_source_audio(mid) == m4a


def test_find_source_audio_missing_raises(isolated_db):
    mid = db.create_meeting("A")
    with pytest.raises(FileNotFoundError):
        db.find_source_audio(mid)


def test_replace_other_source_audio_keeps_upload(isolated_db):
    mid = db.create_meeting("A")
    webm = db.append_audio_chunk(mid, b"webm")
    m4a = db.save_uploaded_audio(mid, "m4a")
    m4a.write_bytes(b"m4a")
    db.replace_other_source_audio(mid, m4a)
    assert m4a.exists()
    assert not webm.exists()
    assert db.find_source_audio(mid) == m4a


def test_progress_round_trip_and_cleared_on_ready(isolated_db):
    mid = db.create_meeting("A")
    db.set_meeting_progress(mid, 2, "Транскрипция…", 47)
    step, label, percent = db.get_meeting_progress(mid)
    assert step == 2
    assert label == "Транскрипция…"
    assert percent == 47

    db.set_meeting_status(mid, "ready")
    step, label, percent = db.get_meeting_progress(mid)
    assert step is None
    assert label is None
    assert percent is None
