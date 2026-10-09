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


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meetings (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
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


def create_meeting(title: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO meetings (title, status, error, created_at) VALUES (?, 'recording', NULL, ?)",
            (title, now),
        )
        return cur.lastrowid


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
            "SELECT id, title, status, created_at, error, "
            "progress_step, progress_label, progress_percent "
            "FROM meetings WHERE id = ?",
            (meeting_id,),
        ).fetchone()
        return dict(row) if row else None


def list_meetings() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, title, status, created_at, error FROM meetings ORDER BY id DESC"
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
