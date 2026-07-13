#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "wcwidth>=0.2.0",
# ]
# ///
"""Stop hook — session finalization and cleanup.

Reads hook stdin JSON: {session_id, data: {transcript_path, total_tokens_used, source}}
Updates SQLite session record with final stats, removes from active sessions in state.json,
cleans stale sessions older than 24h.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add lib/ to import path
LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from state import load_state, save_state

STALE_SESSION_HOURS = 24


def main() -> None:
    # Read hook stdin
    try:
        raw = sys.stdin.read()
        hook_data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, Exception):
        hook_data = {}

    session_id = hook_data.get("session_id", "")

    # Load state
    state = load_state()

    # Finalize session in SQLite — read latest event for final cost/context
    conn = None
    try:
        from db import get_connection, ensure_schema

        conn = get_connection()
        ensure_schema(conn)

        # Get final stats from the latest event for this session
        row = conn.execute(
            """SELECT cost_usd, context_pct FROM events
               WHERE session_id = ? ORDER BY id DESC LIMIT 1""",
            (session_id,),
        ).fetchone()

        if row:
            final_cost = row[0] or 0.0
            final_context = row[1] or 0.0

            # Update session record
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            topic_history = json.dumps(state.get("topic_history", []))
            prompt_count = state.get("prompt_count", 0)

            conn.execute(
                """UPDATE sessions SET
                       last_seen = ?,
                       total_cost = ?,
                       context_peak = MAX(context_peak, ?),
                       topic_history = ?,
                       prompt_count = ?
                   WHERE session_id = ?""",
                (now_iso, final_cost, final_context, topic_history, prompt_count, session_id),
            )
    except Exception as e:
        sys.stderr.write(f"statusline: session_stop SQLite finalize: {e}\n")
    finally:
        if conn:
            conn.close()

    # Remove this session from active sessions in state.json
    sessions = state.get("sessions", {})
    sessions.pop(session_id, None)

    # Clean stale sessions (older than 24h)
    cutoff = time.time() - (STALE_SESSION_HOURS * 3600)
    stale_keys = []
    for sid, info in sessions.items():
        if isinstance(info, dict):
            started = info.get("started_at", "")
            if started:
                try:
                    # datetime.fromisoformat handles the +HHMM offset correctly (Python 3.11+)
                    dt = datetime.fromisoformat(started)
                    # Ensure UTC-aware for comparison
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    t = dt.timestamp()
                    if t < cutoff:
                        stale_keys.append(sid)
                except (ValueError, OverflowError):
                    pass
    for sid in stale_keys:
        sessions.pop(sid, None)

    state["sessions"] = sessions

    # Keep topic_history — persists across sessions for Narrative/Archaeologist themes
    # Reset prompt_count for next session
    state["prompt_count"] = 0

    # Save state
    try:
        save_state(state)
    except Exception as e:
        sys.stderr.write(f"statusline: session_stop save_state: {e}\n")


if __name__ == "__main__":
    main()
