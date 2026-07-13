"""SQLite schema, migrations, and write helpers for claude-statusline."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

DEFAULT_DB_PATH = Path.home() / ".claude" / "local" / "statusline" / "statusline.db"

# Current schema version — bump when adding migrations
SCHEMA_VERSION = 1

_PRAGMAS = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -32000;
PRAGMA mmap_size = 134217728;
PRAGMA busy_timeout = 5000;
"""

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    timestamp_us INTEGER NOT NULL,
    payload TEXT NOT NULL,
    persona TEXT,
    model TEXT,
    cost_usd REAL,
    context_pct REAL
) STRICT;

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    persona TEXT NOT NULL,
    session_number INTEGER NOT NULL,
    title TEXT,
    started_at TEXT NOT NULL,
    last_seen TEXT,
    total_cost REAL DEFAULT 0,
    context_peak REAL DEFAULT 0,
    topic_history TEXT,
    prompt_count INTEGER DEFAULT 0
) STRICT;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp_us);
"""


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open a connection with WAL mode and performance PRAGMAs."""
    path = db_path or DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.executescript(_PRAGMAS)
    return conn


def _get_user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return row[0] if row else 0


def _set_user_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(f"PRAGMA user_version = {version}")


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Apply migrations up to SCHEMA_VERSION."""
    current = _get_user_version(conn)

    if current < 1:
        conn.executescript(_SCHEMA_V1)
        _set_user_version(conn, 1)

    # Future migrations:
    # if current < 2:
    #     conn.executescript(_SCHEMA_V2)
    #     _set_user_version(conn, 2)


def insert_event(
    conn: sqlite3.Connection,
    session_id: str,
    payload_json: str,
    persona: Optional[str] = None,
    model: Optional[str] = None,
    cost_usd: Optional[float] = None,
    context_pct: Optional[float] = None,
    timestamp_us: Optional[int] = None,
) -> int:
    """Insert a status event row. Returns the new row id."""
    import time

    if timestamp_us is None:
        timestamp_us = int(time.time() * 1_000_000)
    cursor = conn.execute(
        """INSERT INTO events (session_id, timestamp_us, payload, persona, model, cost_usd, context_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (session_id, timestamp_us, payload_json, persona, model, cost_usd, context_pct),
    )
    return cursor.lastrowid  # type: ignore[return-value]


def next_session_number(conn: sqlite3.Connection, persona: str) -> int:
    """Get the next sequential session number for a persona.

    Wraps the SELECT + caller's INSERT in a DEFERRED transaction via the
    connection's isolation level to prevent a TOCTOU race when two sessions
    for the same persona start concurrently.  Caller must call conn.close()
    (or commit) after upsert_session to release the lock.
    """
    conn.execute("BEGIN DEFERRED")
    row = conn.execute(
        "SELECT COALESCE(MAX(session_number), 0) + 1 FROM sessions WHERE persona = ?",
        (persona,),
    ).fetchone()
    return row[0] if row else 1


def upsert_session(
    conn: sqlite3.Connection,
    session_id: str,
    persona: str,
    session_number: int,
    started_at: str,
    last_seen: Optional[str] = None,
    total_cost: float = 0.0,
    context_peak: float = 0.0,
    topic_history: Optional[str] = None,
    prompt_count: int = 0,
    title: Optional[str] = None,
) -> None:
    """Insert or update a session record."""
    conn.execute(
        """INSERT INTO sessions (session_id, persona, session_number, title, started_at, last_seen, total_cost, context_peak, topic_history, prompt_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(session_id) DO UPDATE SET
               last_seen = excluded.last_seen,
               total_cost = excluded.total_cost,
               context_peak = MAX(sessions.context_peak, excluded.context_peak),
               topic_history = excluded.topic_history,
               prompt_count = excluded.prompt_count""",
        (session_id, persona, session_number, title, started_at, last_seen, total_cost, context_peak, topic_history, prompt_count),
    )


def lookup_session(conn: sqlite3.Connection, session_id: str) -> Optional[dict]:
    """Look up a session's identity by session_id. Returns None if not found."""
    row = conn.execute(
        "SELECT persona, session_number FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row:
        return {"persona": row[0], "session_number": row[1]}
    return None


def update_session_title(conn: sqlite3.Connection, session_id: str, title: str) -> None:
    """Set session title if not already set. Idempotent."""
    conn.execute(
        "UPDATE sessions SET title = ? WHERE session_id = ? AND (title IS NULL OR title = '')",
        (title, session_id),
    )
