from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from sten import db
from sten.api.app import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "sten.db")
    monkeypatch.setattr(db, "DATA_DIR", tmp_path / "data")
    db.init_db()
    monkeypatch.setattr(
        "sten.api.meetings.start_processing", MagicMock(name="start_processing")
    )
    monkeypatch.setattr(
        "sten.api.meetings.rewrite_item",
        MagicMock(return_value="Переформулированный пункт"),
    )
    with TestClient(create_app()) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_create_meeting_and_chunk(client):
    r = client.post("/api/meetings", json={"title": "Тест"})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Тест"
    assert body["status"] == "recording"
    mid = body["id"]

    r2 = client.post(
        f"/api/meetings/{mid}/chunks",
        content=b"1234",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert r2.status_code == 200
    assert r2.json()["bytes_written"] == 4


def test_stop_calls_start_processing(client, monkeypatch):
    mock_start = MagicMock()
    monkeypatch.setattr("sten.api.meetings.start_processing", mock_start)

    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    r = client.post(f"/api/meetings/{mid}/stop")
    assert r.status_code == 200
    mock_start.assert_called_once_with(mid)
    assert client.get(f"/api/meetings/{mid}/status").json()["status"] == "processing"


def test_stop_conflict_returns_409(client, monkeypatch):
    from sten.api.processing import Conflict

    def raise_conflict(meeting_id):
        raise Conflict("busy")

    monkeypatch.setattr("sten.api.meetings.start_processing", raise_conflict)
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    r = client.post(f"/api/meetings/{mid}/stop")
    assert r.status_code == 409


def test_get_meeting_with_items_and_counts(client):
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    db.replace_items(mid, [("Пункт A", "decision", "Общее"), ("Пункт B", "task", "Общее")])
    items = db.list_items(mid)
    db.set_item_status(items[0]["id"], "accepted")

    r = client.get(f"/api/meetings/{mid}")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "A"
    assert len(body["items"]) == 2
    assert body["counts"] == {"pending": 1, "accepted": 1}


def test_status_endpoint(client):
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    r = client.get(f"/api/meetings/{mid}/status")
    assert r.status_code == 200
    assert r.json() == {"status": "recording", "error": None, "counts": {}}


def test_patch_item_text_and_status(client):
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    db.replace_items(mid, [("Старый", "topic", "Общее")])
    item_id = db.list_items(mid)[0]["id"]

    r = client.patch(
        f"/api/meetings/{mid}/items/{item_id}",
        json={"text": "Новый", "status": "accepted"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "Новый"
    assert body["status"] == "accepted"
    assert db.get_meeting(mid)["status"] == "consensus"


def test_rewrite_item_endpoint(client, monkeypatch):
    mock_rewrite = MagicMock(return_value="Новая формулировка")
    monkeypatch.setattr("sten.api.meetings.rewrite_item", mock_rewrite)

    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    db.replace_items(mid, [("Старый пункт", "decision", "Общее")])
    item_id = db.list_items(mid)[0]["id"]

    r = client.post(
        f"/api/meetings/{mid}/items/{item_id}/rewrite",
        json={"objection": "бюджет не согласован"},
    )
    assert r.status_code == 200
    assert r.json()["text"] == "Новая формулировка"
    mock_rewrite.assert_called_once()
    assert mock_rewrite.call_args.args[0] == "Старый пункт"
    assert mock_rewrite.call_args.args[1] == "бюджет не согласован"


def test_delete_item_endpoint(client):
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    db.replace_items(mid, [("A", "topic", "Общее"), ("B", "topic", "Общее")])
    item_id = db.list_items(mid)[0]["id"]

    r = client.delete(f"/api/meetings/{mid}/items/{item_id}")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "id": item_id}
    assert [i["text"] for i in db.list_items(mid)] == ["B"]


def test_transcript_endpoint(client, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path / "data")
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]

    r0 = client.get(f"/api/meetings/{mid}/transcript")
    assert r0.status_code == 200
    assert r0.json()["available"] is False
    assert r0.json()["turns"] == []
    assert r0.json()["diarized"] is False

    out = tmp_path / "data" / "meetings" / str(mid)
    out.mkdir(parents=True)
    (out / "transcript.txt").write_text("Привет, это тест.", encoding="utf-8")
    (out / "transcript.json").write_text(
        '[{"start":0,"end":1,"text":"Привет, это тест.","speaker":null}]',
        encoding="utf-8",
    )

    r1 = client.get(f"/api/meetings/{mid}/transcript")
    assert r1.status_code == 200
    body = r1.json()
    assert body["available"] is True
    assert body["diarized"] is False
    assert body["turns"][0]["text"] == "Привет, это тест."


def test_transcript_with_speakers(client, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path / "data")
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    out = tmp_path / "data" / "meetings" / str(mid)
    out.mkdir(parents=True)
    (out / "transcript.json").write_text(
        "["
        '{"start":0,"end":1,"text":"Привет","speaker":"Спикер 1"},'
        '{"start":1,"end":2,"text":"Пока","speaker":"Спикер 2"}'
        "]",
        encoding="utf-8",
    )
    (out / "transcript.txt").write_text(
        "Спикер 1: Привет\n\nСпикер 2: Пока", encoding="utf-8"
    )

    r = client.get(f"/api/meetings/{mid}/transcript")
    assert r.status_code == 200
    body = r.json()
    assert body["diarized"] is True
    assert [t["speaker"] for t in body["turns"]] == ["Спикер 1", "Спикер 2"]


def test_diarize_endpoint(client, monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr("sten.api.meetings.start_diarize", mock)
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    r = client.post(f"/api/meetings/{mid}/diarize")
    assert r.status_code == 200
    assert r.json() == {"id": mid, "status": "diarizing"}
    mock.assert_called_once_with(mid)


def test_get_missing_meeting_404(client):
    assert client.get("/api/meetings/999").status_code == 404
