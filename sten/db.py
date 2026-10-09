import getpass
import hashlib
import hmac
import os
import secrets
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sten.config import DATA_DIR, DB_PATH

ALLOWED_AUDIO_EXTS = frozenset({
    "webm", "m4a", "caf", "mp3", "wav", "ogg", "oga",
    "aac", "flac", "mp4", "mpeg", "mpga", "m4b",
})
MAX_AUDIO_BYTES = 512 * 1024 * 1024
_SOURCE_AUDIO_ORDER = (
    "audio.webm",
    "audio.m4a",
    "audio.caf",
    "audio.mp3",
    "audio.ogg",
    "audio.oga",
    "audio.aac",
    "audio.flac",
    "audio.mp4",
    "audio.mpeg",
    "audio.mpga",
    "audio.m4b",
    "audio.wav",
)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    rounds = 200_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return f"pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_hex, digest_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              name_key TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
              token TEXT PRIMARY KEY,
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meetings (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER REFERENCES users(id),
              title TEXT NOT NULL,
              status TEXT NOT NULL,
              error TEXT,
              created_at TEXT NOT NULL,
              progress_step INTEGER,
              progress_label TEXT,
              progress_percent INTEGER
            );
            CREATE TABLE IF NOT EXISTS items (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
              text TEXT NOT NULL,
              category TEXT NOT NULL,
              theme TEXT NOT NULL DEFAULT 'Общее',
              status TEXT NOT NULL,
              position INTEGER NOT NULL
            );
            """
        )
        item_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(items)").fetchall()
        }
        if "theme" not in item_cols:
            conn.execute(
                "ALTER TABLE items ADD COLUMN theme TEXT NOT NULL DEFAULT 'Общее'"
            )
        meeting_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(meetings)").fetchall()
        }
        if "progress_step" not in meeting_cols:
            conn.execute("ALTER TABLE meetings ADD COLUMN progress_step INTEGER")
        if "progress_label" not in meeting_cols:
            conn.execute("ALTER TABLE meetings ADD COLUMN progress_label TEXT")
        if "progress_percent" not in meeting_cols:
            conn.execute("ALTER TABLE meetings ADD COLUMN progress_percent INTEGER")
        if "user_id" not in meeting_cols:
            conn.execute("ALTER TABLE meetings ADD COLUMN user_id INTEGER REFERENCES users(id)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_meetings_user ON meetings(user_id)"
        )
        _assign_orphan_meetings(conn)


def _owner_name() -> str:
    return os.environ.get("STEN_OWNER_NAME", getpass.getuser()).strip() or "owner"


def _name_key(name: str) -> str:
    return name.casefold()


def _assign_orphan_meetings(conn: sqlite3.Connection) -> None:
    """Give pre-user meetings to the machine owner, not to the next person who registers."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM meetings WHERE user_id IS NULL"
    ).fetchone()
    if row["n"] == 0:
        return
    name = _owner_name()
    owner = conn.execute(
        "SELECT id FROM users WHERE name_key = ?", (_name_key(name),)
    ).fetchone()
    if owner is None:
        password = secrets.token_urlsafe(12)
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            "INSERT INTO users (name, name_key, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (name, _name_key(name), hash_password(password), now),
        )
        user_id = int(cur.lastrowid)
        path = DATA_DIR / ".owner-password"
        path.write_text(f"{name}\n{password}\n", encoding="utf-8")
        path.chmod(0o600)
    else:
        user_id = int(owner["id"])
    conn.execute(
        "UPDATE meetings SET user_id = ? WHERE user_id IS NULL",
        (user_id,),
    )


def create_user(name: str, password: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (name, name_key, password_hash, created_at) "
                "VALUES (?, ?, ?, ?)",
                (name, _name_key(name), hash_password(password), now),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("name taken") from exc
        user_id = int(cur.lastrowid)
        row = conn.execute(
            "SELECT id, name, created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return dict(row)


def authenticate(name: str, password: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, name, password_hash, created_at FROM users WHERE name_key = ?",
            (_name_key(name),),
        ).fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            return None
        return {"id": row["id"], "name": row["name"], "created_at": row["created_at"]}


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
            (token, user_id, now),
        )
    return token


def get_user_by_session(token: str) -> dict | None:
    if not token:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT u.id, u.name, u.created_at FROM sessions s "
            "JOIN users u ON u.id = s.user_id WHERE s.token = ?",
            (token,),
        ).fetchone()
        return dict(row) if row else None


def delete_session(token: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def create_meeting(title: str, user_id: int | None = None) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        if user_id is None:
            user_id = _fallback_user_id(conn)
        cur = conn.execute(
            "INSERT INTO meetings (user_id, title, status, error, created_at) "
            "VALUES (?, ?, 'recording', NULL, ?)",
            (user_id, title, now),
        )
        return int(cur.lastrowid)


def _fallback_user_id(conn: sqlite3.Connection) -> int:
    """Owner for callers that predate per-user meetings (tests, local scripts)."""
    row = conn.execute(
        "SELECT id FROM users WHERE name_key = ?", (_name_key("local"),)
    ).fetchone()
    if row is not None:
        return int(row["id"])
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO users (name, name_key, password_hash, created_at) VALUES (?, ?, ?, ?)",
        ("local", _name_key("local"), hash_password(secrets.token_urlsafe(18)), now),
    )
    return int(cur.lastrowid)


def delete_meeting(meeting_id: int) -> bool:
    """Remove the meeting row, its items, and files on disk."""
    with _connect() as conn:
        cur = conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
        deleted = cur.rowcount > 0
    folder = DATA_DIR / "meetings" / str(meeting_id)
    if folder.is_dir():
        shutil.rmtree(folder)
    return deleted


def set_meeting_title(meeting_id: int, title: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE meetings SET title = ? WHERE id = ?",
            (title, meeting_id),
        )


def get_meeting(meeting_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, user_id, title, status, created_at, error, "
            "progress_step, progress_label, progress_percent "
            "FROM meetings WHERE id = ?",
            (meeting_id,),
        ).fetchone()
        return dict(row) if row else None


def list_meetings(user_id: int | None = None) -> list[dict]:
    with _connect() as conn:
        if user_id is None:
            rows = conn.execute(
                "SELECT id, title, status, created_at, error FROM meetings ORDER BY id DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, title, status, created_at, error FROM meetings "
                "WHERE user_id = ? ORDER BY id DESC",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]


def set_meeting_status(
    meeting_id: int, status: str, error: str | None = None
) -> None:
    with _connect() as conn:
        if status in ("ready", "error", "recording"):
            conn.execute(
                "UPDATE meetings SET status = ?, error = ?, "
                "progress_step = NULL, progress_label = NULL, "
                "progress_percent = NULL WHERE id = ?",
                (status, error, meeting_id),
            )
        else:
            conn.execute(
                "UPDATE meetings SET status = ?, error = ? WHERE id = ?",
                (status, error, meeting_id),
            )


def set_meeting_progress(
    meeting_id: int,
    step: int | None,
    label: str | None,
    percent: int | None = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE meetings SET progress_step = ?, progress_label = ?, "
            "progress_percent = ? WHERE id = ?",
            (step, label, percent, meeting_id),
        )


def get_meeting_progress(
    meeting_id: int,
) -> tuple[int | None, str | None, int | None]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT progress_step, progress_label, progress_percent "
            "FROM meetings WHERE id = ?",
            (meeting_id,),
        ).fetchone()
        if row is None:
            return None, None, None
        return row["progress_step"], row["progress_label"], row["progress_percent"]


def save_uploaded_audio(meeting_id: int, ext: str) -> Path:
    clean = ext.lower().lstrip(".")
    if clean not in ALLOWED_AUDIO_EXTS:
        raise ValueError(f"unsupported audio extension: {ext}")
    audio_dir = DATA_DIR / "meetings" / str(meeting_id)
    audio_dir.mkdir(parents=True, exist_ok=True)
    return audio_dir / f"audio.{clean}"


def replace_other_source_audio(meeting_id: int, keep: Path) -> None:
    audio_dir = DATA_DIR / "meetings" / str(meeting_id)
    keep_resolved = keep.resolve()
    for name in _SOURCE_AUDIO_ORDER:
        path = audio_dir / name
        if path.is_file() and path.resolve() != keep_resolved:
            path.unlink()


def find_source_audio(meeting_id: int) -> Path:
    audio_dir = DATA_DIR / "meetings" / str(meeting_id)
    for name in _SOURCE_AUDIO_ORDER:
        path = audio_dir / name
        if path.is_file() and path.stat().st_size > 0:
            return path
    raise FileNotFoundError(f"no source audio for meeting {meeting_id}")


def append_audio_chunk(meeting_id: int, data: bytes) -> Path:
    audio_dir = DATA_DIR / "meetings" / str(meeting_id)
    audio_dir.mkdir(parents=True, exist_ok=True)
    path = audio_dir / "audio.webm"
    with open(path, "ab") as f:
        f.write(data)
    return path


def replace_items(meeting_id: int, items: list[tuple[str, str, str]]) -> None:
    """items: list of (text, category, theme)."""
    with _connect() as conn:
        conn.execute("DELETE FROM items WHERE meeting_id = ?", (meeting_id,))
        for position, (text, category, theme) in enumerate(items):
            conn.execute(
                "INSERT INTO items (meeting_id, text, category, theme, status, position) "
                "VALUES (?, ?, ?, ?, 'pending', ?)",
                (meeting_id, text, category, theme or "Общее", position),
            )


def list_items(meeting_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, meeting_id, text, category, theme, status, position "
            "FROM items WHERE meeting_id = ? ORDER BY position",
            (meeting_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def update_item_text(item_id: int, text: str) -> dict:
    with _connect() as conn:
        conn.execute("UPDATE items SET text = ? WHERE id = ?", (text, item_id))
        row = conn.execute(
            "SELECT id, meeting_id, text, category, theme, status, position "
            "FROM items WHERE id = ?",
            (item_id,),
        ).fetchone()
        return dict(row)


def set_item_status(item_id: int, status: str) -> dict:
    with _connect() as conn:
        conn.execute("UPDATE items SET status = ? WHERE id = ?", (status, item_id))
        row = conn.execute(
            "SELECT id, meeting_id, text, category, theme, status, position "
            "FROM items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if status == "pending":
            meeting = conn.execute(
                "SELECT status FROM meetings WHERE id = ?",
                (row["meeting_id"],),
            ).fetchone()
            if meeting and meeting["status"] == "consensus":
                conn.execute(
                    "UPDATE meetings SET status = 'ready' WHERE id = ?",
                    (row["meeting_id"],),
                )
        return dict(row)


def delete_item(item_id: int) -> int | None:
    """Delete item; return meeting_id if deleted, else None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT meeting_id FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        if row is None:
            return None
        meeting_id = int(row["meeting_id"])
        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        return meeting_id


def count_item_statuses(meeting_id: int) -> dict[str, int]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM items WHERE meeting_id = ? GROUP BY status",
            (meeting_id,),
        ).fetchall()
        return {row["status"]: row["cnt"] for row in rows}


def maybe_mark_consensus(meeting_id: int) -> None:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT status FROM items WHERE meeting_id = ?",
            (meeting_id,),
        ).fetchall()
        if not rows:
            return
        if all(row["status"] == "accepted" for row in rows):
            conn.execute(
                "UPDATE meetings SET status = 'consensus' WHERE id = ?",
                (meeting_id,),
            )
