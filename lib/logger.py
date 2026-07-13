"""Dual JSONL + SQLite writer for claude-statusline.

JSONL: synchronous append with flock (< 1ms target).
SQLite: async via os.fork() — parent returns immediately.
"""

from __future__ import annotations

import json
import os
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

# Auto-reap forked children to prevent zombie accumulation.
# Status events fire ~every 300ms — without this, 12K zombies/hour.
if hasattr(signal, "SIGCHLD"):
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)

if TYPE_CHECKING:
    from payload import StatusPayload

EVENTS_DIR = Path.home() / ".claude" / "local" / "statusline" / "events"


def _jsonl_path() -> Path:
    """Monthly JSONL file: YYYY-MM.jsonl."""
    now = datetime.now(timezone.utc)
    return EVENTS_DIR / f"{now.strftime('%Y-%m')}.jsonl"


def _try_flock(fd: int) -> None:
    """Acquire exclusive flock. No-op on platforms without fcntl."""
    try:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX)
    except (ImportError, OSError):
        pass


def _try_unflock(fd: int) -> None:
    """Release flock. No-op on platforms without fcntl."""
    try:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)
    except (ImportError, OSError):
        pass


def _write_jsonl(session_id: str, raw_payload: dict, ts_iso: str) -> None:
    """Append one JSONL line. Full payload, zero truncation."""
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _jsonl_path()
    line = json.dumps(
        {
            "ts": ts_iso,
            "sid": session_id,
            "payload": raw_payload,
        },
        separators=(",", ":"),
    )
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        _try_flock(fd)
        os.write(fd, (line + "\n").encode())
    finally:
        _try_unflock(fd)
        os.close(fd)


def _write_sqlite(session_id: str, payload_json: str, persona: str, model: str,
                   cost: float, ctx_pct: float | None, timestamp_us: int) -> None:
    """Write to SQLite in a forked child.

    INVARIANT: Parent must never hold an open SQLite connection when forking.
    Imports db lazily to avoid circular deps.
    """
    try:
        from .db import ensure_schema, get_connection, insert_event
    except ImportError:
        from db import ensure_schema, get_connection, insert_event

    try:
        conn = get_connection()
        ensure_schema(conn)
        insert_event(
            conn,
            session_id=session_id,
            payload_json=payload_json,
            persona=persona,
            model=model,
            cost_usd=cost,
            context_pct=ctx_pct,
            timestamp_us=timestamp_us,
        )
        conn.close()
    except Exception as e:
        # Child must not propagate errors to parent — but log for diagnostics
        import sys as _sys
        _sys.stderr.write(f"statusline: logger SQLite write: {e}\n")


def log_payload(payload: "StatusPayload", session_id: str, persona: str) -> None:
    """Log a status payload via JSONL (sync) + SQLite (async fork).

    Args:
        payload: Parsed StatusPayload with _raw dict.
        session_id: Current session identifier.
        persona: Active persona slug.
    """
    # Capture timestamp ONCE — used by both JSONL and SQLite to avoid divergence
    import time
    now = datetime.now(timezone.utc)
    ts_iso = now.isoformat()
    timestamp_us = int(time.time() * 1_000_000)

    raw = payload._raw if payload._raw else {}
    payload_json = json.dumps(raw, separators=(",", ":"))

    # Extract fields for SQLite columns
    model = payload.model.id if payload.model else ""
    cost = payload.cost.total_cost_usd if payload.cost else 0.0
    ctx_pct: float | None = None
    if payload.context_window and payload.context_window.used_percentage is not None:
        ctx_pct = payload.context_window.used_percentage

    # 1. Synchronous JSONL write (must be fast)
    try:
        _write_jsonl(session_id, raw, ts_iso)
    except Exception as e:
        import sys as _sys
        _sys.stderr.write(f"statusline: logger JSONL write: {e}\n")

    # 2. Async SQLite write via fork
    if not hasattr(os, "fork"):
        # No fork (Windows) — write synchronously as fallback
        _write_sqlite(session_id, payload_json, persona, model, cost, ctx_pct, timestamp_us)
        return

    try:
        pid = os.fork()
    except OSError:
        # Fork failed — write synchronously
        _write_sqlite(session_id, payload_json, persona, model, cost, ctx_pct, timestamp_us)
        return

    if pid == 0:
        # Child process
        try:
            _write_sqlite(session_id, payload_json, persona, model, cost, ctx_pct, timestamp_us)
        finally:
            os._exit(0)
    # Parent returns immediately — child is fire-and-forget
