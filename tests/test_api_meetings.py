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
        registered = c.post(
            "/api/auth/register",
            json={"name": "tester", "password": "secret1"},
        )
        assert registered.status_code == 200, registered.text
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


def test_patch_meeting_renames_title(client):
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    r = client.patch(f"/api/meetings/{mid}", json={"title": "  Планёрка  "})
    assert r.status_code == 200
    assert r.json()["title"] == "Планёрка"
    assert client.get(f"/api/meetings/{mid}").json()["title"] == "Планёрка"


def test_delete_meeting_endpoint(client):
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    db.append_audio_chunk(mid, b"abc")
    r = client.delete(f"/api/meetings/{mid}")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "id": mid}
    assert client.get(f"/api/meetings/{mid}").status_code == 404


def test_delete_meeting_missing_404(client):
    r = client.delete("/api/meetings/999")
    assert r.status_code == 404


def test_delete_meeting_while_busy_409(client, monkeypatch):
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    monkeypatch.setattr("sten.api.meetings.is_busy", lambda meeting_id: True)
    r = client.delete(f"/api/meetings/{mid}")
    assert r.status_code == 409
    assert client.get(f"/api/meetings/{mid}").status_code == 200


def test_patch_meeting_rejects_blank_title(client):
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    r = client.patch(f"/api/meetings/{mid}", json={"title": "   "})
    assert r.status_code == 400
    assert client.get(f"/api/meetings/{mid}").json()["title"] == "A"


def test_status_endpoint(client):
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    r = client.get(f"/api/meetings/{mid}/status")
    assert r.status_code == 200
    assert r.json() == {
        "status": "recording",
        "error": None,
        "counts": {},
        "progress": None,
    }


def test_upload_audio_saves_m4a_and_starts_processing(client, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path / "data")
    mock_start = MagicMock()
    monkeypatch.setattr("sten.api.meetings.start_processing", mock_start)

    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    r = client.post(
        f"/api/meetings/{mid}/audio",
        files={"file": ("memo.m4a", b"fake-audio", "audio/mp4")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == mid
    assert body["status"] == "processing"
    assert body["filename"] == "audio.m4a"
    assert body["bytes"] == len(b"fake-audio")
    saved = tmp_path / "data" / "meetings" / str(mid) / "audio.m4a"
    assert saved.read_bytes() == b"fake-audio"
    mock_start.assert_called_once_with(mid)
    status = client.get(f"/api/meetings/{mid}/status").json()
    assert status["status"] == "processing"


def test_upload_audio_replaces_existing_webm(client, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path / "data")
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    db.append_audio_chunk(mid, b"old-webm")
    r = client.post(
        f"/api/meetings/{mid}/audio",
        files={"file": ("memo.m4a", b"new-m4a", "audio/mp4")},
    )
    assert r.status_code == 200
    folder = tmp_path / "data" / "meetings" / str(mid)
    assert (folder / "audio.m4a").read_bytes() == b"new-m4a"
    assert not (folder / "audio.webm").exists()


def test_upload_audio_extension_from_caf_filename(client, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path / "data")
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    r = client.post(
        f"/api/meetings/{mid}/audio",
        files={"file": ("voice.caf", b"caff-bytes", "")},
    )
    assert r.status_code == 200
    assert r.json()["filename"] == "audio.caf"
    assert (tmp_path / "data" / "meetings" / str(mid) / "audio.caf").is_file()


def test_upload_audio_mime_only_blob_becomes_mp3(client, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path / "data")
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    r = client.post(
        f"/api/meetings/{mid}/audio",
        files={"file": ("blob", b"\xff\xfb" + b"\x00" * 20, "audio/mpeg")},
    )
    assert r.status_code == 200
    assert r.json()["filename"] == "audio.mp3"


def test_upload_telemost_webm_and_mkv(client, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path / "data")
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    webm = b"\x1a\x45\xdf\xa3" + b"telemost-video"
    r = client.post(
        f"/api/meetings/{mid}/audio",
        files={"file": ("meeting.webm", webm, "video/webm")},
    )
    assert r.status_code == 200
    assert r.json()["filename"] == "audio.webm"
    saved = tmp_path / "data" / "meetings" / str(mid) / "audio.webm"
    assert saved.read_bytes() == webm

    mid2 = client.post("/api/meetings", json={"title": "B"}).json()["id"]
    r = client.post(
        f"/api/meetings/{mid2}/audio",
        files={"file": ("talk.mkv", b"matroska", "video/x-matroska")},
    )
    assert r.status_code == 200
    assert r.json()["filename"] == "audio.mkv"


def test_upload_audio_rejects_exe(client):
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    r = client.post(
        f"/api/meetings/{mid}/audio",
        files={"file": ("malware.exe", b"MZ", "application/octet-stream")},
    )
    assert r.status_code == 400


def test_upload_audio_empty_file_400(client):
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    r = client.post(
        f"/api/meetings/{mid}/audio",
        files={"file": ("empty.m4a", b"", "audio/mp4")},
    )
    assert r.status_code == 400


def test_upload_audio_missing_meeting_404(client):
    r = client.post(
        "/api/meetings/999/audio",
        files={"file": ("memo.m4a", b"data", "audio/mp4")},
    )
    assert r.status_code == 404


def test_upload_audio_oversize_413(client, monkeypatch):
    monkeypatch.setattr("sten.api.meetings.MAX_AUDIO_BYTES", 10)
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    r = client.post(
        f"/api/meetings/{mid}/audio",
        files={"file": ("big.m4a", b"0123456789abcdef", "audio/mp4")},
    )
    assert r.status_code == 413


def test_status_progress_while_processing(client):
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    db.set_meeting_status(mid, "processing")
    db.set_meeting_progress(mid, 2, "Транскрипция…")
    r = client.get(f"/api/meetings/{mid}/status")
    assert r.status_code == 200
    assert r.json()["progress"] == {
        "step": 2,
        "total": 4,
        "percent": 40,
        "label": "Транскрипция…",
    }


def test_status_progress_uses_stored_percent(client):
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    db.set_meeting_status(mid, "processing")
    db.set_meeting_progress(mid, 2, "Транскрипция…", 47)
    r = client.get(f"/api/meetings/{mid}/status")
    assert r.json()["progress"]["percent"] == 47
    assert r.json()["progress"]["label"] == "Транскрипция…"


def test_status_progress_ready_is_100(client):
    mid = client.post("/api/meetings", json={"title": "A"}).json()["id"]
    db.set_meeting_status(mid, "ready")
    r = client.get(f"/api/meetings/{mid}/status")
    assert r.json()["progress"] == {
        "step": 4,
        "total": 4,
        "percent": 100,
        "label": "Готово",
    }


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
    assert body["text"] == "[00:00]\nПривет, это тест."


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
    assert body["text"] == "[00:00]\nСпикер 1: Привет\n\nСпикер 2: Пока"


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


def test_list_meetings_hides_empty_recordings(client):
    empty = client.post("/api/meetings", json={"title": "Пустая"}).json()["id"]
    ready = client.post("/api/meetings", json={"title": "Готовая"}).json()["id"]
    db.set_meeting_status(ready, "ready")
    with_audio = client.post("/api/meetings", json={"title": "С файлом"}).json()["id"]
    db.save_uploaded_audio(with_audio, "webm").write_bytes(b"abc")

    listed = client.get("/api/meetings")
    assert listed.status_code == 200
    ids = [item["id"] for item in listed.json()]
    assert ids == sorted(ids, reverse=True)
    assert ready in ids
    assert with_audio in ids
    assert empty not in ids
    assert "error" not in listed.json()[0]

    included = client.get("/api/meetings", params={"include_id": empty})
    assert empty in [item["id"] for item in included.json()]


def _ready_meeting(client, tmp_path):
    mid = client.post("/api/meetings", json={"title": "Планёрка"}).json()["id"]
    out = tmp_path / "data" / "meetings" / str(mid)
    out.mkdir(parents=True, exist_ok=True)
    (out / "audio.webm").write_bytes(b"webm-bytes")
    (out / "transcript.json").write_text(
        '[{"start":0,"end":1.2,"text":"Привет","speaker":"Спикер 1"}]',
        encoding="utf-8",
    )
    (out / "transcript.txt").write_text("Спикер 1: Привет", encoding="utf-8")
    (out / "speakers.json").write_text(
        '{"speakers": ["Спикер 1"]}', encoding="utf-8"
    )
    (out / "summary.json").write_text(
        """
        {"items": [], "report": {
          "title": "Тема", "summary": "Кратко", "outcome": "Дальше",
          "participants": [{"speaker": "Спикер 1", "role": "", "name": ""}],
          "topics": [], "decisions": [], "tasks": []
        }}
        """,
        encoding="utf-8",
    )
    return mid


def test_report_audio_and_export(client, tmp_path):
    mid = _ready_meeting(client, tmp_path)
    report = client.get(f"/api/meetings/{mid}/report")
    assert report.status_code == 200
    assert report.json()["title"] == "Тема"
    assert "Кратко" in report.json()["text"]

    audio = client.get(f"/api/meetings/{mid}/audio")
    assert audio.status_code == 200
    assert audio.content == b"webm-bytes"
    assert audio.headers["content-type"].startswith("audio/webm")

    exported = client.get(f"/api/meetings/{mid}/export", params={"format": "srt"})
    assert exported.status_code == 200
    assert "Спикер 1: Привет" in exported.text
    assert "filename*=UTF-8''" in exported.headers["content-disposition"]

    docx = client.get(f"/api/meetings/{mid}/export", params={"format": "docx"})
    assert docx.status_code == 200
    assert docx.content[:2] == b"PK"


def test_speaker_rename_and_blocked_delete(client, tmp_path):
    mid = _ready_meeting(client, tmp_path)
    renamed = client.post(
        f"/api/meetings/{mid}/speakers/rename",
        json={"source": "Спикер 1", "target": "Сергей"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["speakers"] == [{"name": "Сергей", "count": 1}]
    assert renamed.json()["report"]["participants"][0]["speaker"] == "Сергей"

    blocked = client.post(
        f"/api/meetings/{mid}/speakers/delete",
        json={"name": "Сергей"},
    )
    assert blocked.status_code == 409
    assert "Сначала замените" in blocked.json()["detail"]
