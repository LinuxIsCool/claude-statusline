#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "wcwidth>=0.2.0",
# ]
# ///
"""SessionStart hook — persona detection, session registration, memory cache.

Reads hook stdin JSON: {session_id, cwd, data: {source, model, context_tokens_available}}
Registers session in SQLite + state.json, detects persona, assigns session number.
Forks a child process to populate memory cache (non-blocking).
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

# Add lib/ to import path
LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from db import get_connection, ensure_schema, next_session_number, upsert_session
from state import load_state, save_state, detect_persona


def main() -> None:
    # Read hook stdin
    try:
        raw = sys.stdin.read()
        hook_data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, Exception):
        hook_data = {}

    session_id = hook_data.get("session_id", "")
    data = hook_data.get("data", {})
    model = data.get("model", "")

    # Detect persona — prefer agent_type from hook data (most reliable)
    persona = detect_persona()
    agent_type = hook_data.get("agent_type", "") or data.get("agent_type", "")
    if ":" in agent_type:
        slug_from_agent = agent_type.rsplit(":", 1)[-1].strip()
        if slug_from_agent:
            persona = slug_from_agent

    # Load state
    state = load_state()

    # Get session number from SQLite
    conn = None
    try:
        conn = get_connection()
        ensure_schema(conn)
        # next_session_number opens a DEFERRED transaction — holds the lock
        # until we commit, preventing concurrent session starts from racing.
        session_number = next_session_number(conn, persona)

        # Register session in SQLite (still within the transaction)
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        upsert_session(
            conn,
            session_id=session_id,
            persona=persona,
            session_number=session_number,
            started_at=now_iso,
            last_seen=now_iso,
        )
        conn.execute("COMMIT")
    except Exception as e:
        sys.stderr.write(f"statusline: session_start SQLite registration: {e}\n")
        # Per-persona fallback: find max session_number for this persona from sessions dict
        sessions = state.get("sessions", {})
        max_for_persona = max(
            (s.get("session_number", 0) for s in sessions.values() if s.get("persona") == persona),
            default=state.get("session_number", 0),
        )
        session_number = max_for_persona + 1
    finally:
        if conn:
            conn.close()

    # Update state.json
    state["session_id"] = session_id
    state["persona"] = persona
    state["session_number"] = session_number
    state["prompt_count"] = 0
    state["topic_history"] = []

    # Reset grid for new session (per-session file, not state.json)
    import time as _time
    try:
        from grid import Grid, Cell
        from grid_io import save_grid
        from grid_mapper import map_event, get_weight
        emoji, key = map_event("SessionStart")
        weight = get_weight(key)
        grid = Grid()
        grid.append(Cell(emoji=emoji, key=key, weight=weight, ts=_time.time()))
        save_grid(session_id, grid)
    except Exception as e:
        sys.stderr.write(f"statusline: session_start grid init: {e}\n")

    # Register in active sessions dict
    sessions = state.get("sessions", {})
    sessions[session_id] = {
        "persona": persona,
        "session_number": session_number,
        "model": model,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "cost": 0.0,
    }
    state["sessions"] = sessions

    # Save state (before fork — child will also write)
    try:
        save_state(state)
    except Exception as e:
        sys.stderr.write(f"statusline: session_start save_state: {e}\n")

    # Fork child to populate memory cache (non-blocking)
    # Parent returns immediately so hook doesn't block session start
    try:
        # Auto-reap children to prevent zombies
        signal.signal(signal.SIGCHLD, signal.SIG_IGN)
        pid = os.fork()
        if pid == 0:
            # Child process — query all memory backends, write to state.
            # IMPORTANT: query_all() takes 2-10s. We load state AFTER the
            # queries complete so we pick up any state changes written by
            # user_prompt.py or other hooks during that window. The atomic
            # tmpfile+rename in save_state() ensures we don't corrupt state
            # if another process writes concurrently — worst case we lose
            # one topic history entry (acceptable for a cache update).
            try:
                from memory import query_all
                cache = query_all()
                # Re-load state AFTER queries — captures any writes that
                # happened while queries were running (user_prompt.py etc.)
                child_state = load_state()
                child_state["memory_cache"] = cache
                save_state(child_state)
            except Exception as e:
                import sys as _sys
                _sys.stderr.write(f"statusline: session_start memory cache: {e}\n")
            os._exit(0)
    except (OSError, AttributeError):
        # Fork not available (Windows) or failed — skip memory population
        pass

    # Output hook response with session identity context
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": f"Session {persona}:{session_number} (id: {session_id[:8]})",
        }
    }
    print(json.dumps(output), flush=True)


if __name__ == "__main__":
    main()
