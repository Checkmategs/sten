from fastapi.testclient import TestClient

from sten.api.app import create_app


def test_register_login_and_isolate_meetings(tmp_path, monkeypatch):
    from sten import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "sten.db")
    monkeypatch.setattr(db, "DATA_DIR", tmp_path / "data")
    db.init_db()

    with TestClient(create_app()) as alice, TestClient(create_app()) as bob:
        assert alice.get("/api/meetings").status_code == 401

        registered = alice.post(
            "/api/auth/register",
            json={"name": "Алиса", "password": "secret1"},
        )
        assert registered.status_code == 200
        assert registered.json()["name"] == "Алиса"
        assert alice.get("/api/auth/me").json()["name"] == "Алиса"

        taken = bob.post(
            "/api/auth/register",
            json={"name": "алиса", "password": "secret2"},
        )
        assert taken.status_code == 409

        assert (
            bob.post(
                "/api/auth/register",
                json={"name": "Борис", "password": "secret2"},
            ).status_code
            == 200
        )

        mid = alice.post("/api/meetings", json={"title": "Планёрка"}).json()["id"]
        alice.post(
            f"/api/meetings/{mid}/chunks",
            content=b"audio",
            headers={"Content-Type": "application/octet-stream"},
        )

        alice_ids = [row["id"] for row in alice.get("/api/meetings").json()]
        assert mid in alice_ids
        assert bob.get("/api/meetings").json() == []
        assert bob.get(f"/api/meetings/{mid}").status_code == 404
        assert bob.delete(f"/api/meetings/{mid}").status_code == 404
        assert alice.get(f"/api/meetings/{mid}").status_code == 200

        alice.post("/api/auth/logout")
        assert alice.get("/api/auth/me").status_code == 401
        logged_in = alice.post(
            "/api/auth/login",
            json={"name": "алиса", "password": "secret1"},
        )
        assert logged_in.status_code == 200
        assert mid in [row["id"] for row in alice.get("/api/meetings").json()]
        assert (
            alice.post(
                "/api/auth/login",
                json={"name": "Алиса", "password": "wrong-pass"},
            ).status_code
            == 401
        )


def test_existing_meetings_belong_to_owner(tmp_path, monkeypatch):
    import sqlite3

    from sten import db

    db_path = tmp_path / "sten.db"
    data = tmp_path / "data"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(db, "DATA_DIR", data)
    monkeypatch.setenv("STEN_OWNER_NAME", "nineone")
    data.mkdir()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE meetings (id INTEGER PRIMARY KEY, title TEXT, status TEXT, "
        "error TEXT, created_at TEXT)"
    )
    conn.execute(
        "INSERT INTO meetings (title, status, error, created_at) VALUES (?, ?, NULL, ?)",
        ("Старая", "ready", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    db.init_db()
    owner = (data / ".owner-password").read_text(encoding="utf-8").splitlines()
    assert owner[0] == "nineone"
    assert db.list_meetings()[0]["title"] == "Старая"

    with TestClient(create_app()) as client:
        stranger = client.post(
            "/api/auth/register",
            json={"name": "Гость", "password": "secret1"},
        )
        assert stranger.status_code == 200
        assert client.get("/api/meetings").json() == []

        client.post("/api/auth/logout")
        logged = client.post(
            "/api/auth/login",
            json={"name": "nineone", "password": owner[1]},
        )
        assert logged.status_code == 200
        assert [row["title"] for row in client.get("/api/meetings").json()] == ["Старая"]
