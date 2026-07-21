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
