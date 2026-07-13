"""Resolve the stable Claude Code root PID for a session.

Problem (task-552 Q1): the statusline's PID column changes during a
session because `compute_identity` falls back to `os.getppid()`, which
returns the *immediate* parent of whichever forked the render — main
claude process, hook runner, subagent dispatcher, tool exec context,
etc. The parent rotates render-to-render.

Solution: walk up the process tree from getppid() looking for a
process whose `comm` is "claude" (the Claude Code CLI binary). Once
found, cache the result keyed by session_id so the walk happens
exactly once per session.

Linux-only (relies on /proc). Statusline is Linux-only today; if it
ever ports, this module's resolve() will fall back to getppid() on
OSError, which preserves the v0.5.2 behavior.

References:
  - task-552 Phase 2 — Identity stability
  - components.compute_identity (the only caller)
  - 2026-06-01 design chat Q1
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

# Cache layout. Per-session because each Claude Code session has its
# own stable root PID; cross-session sharing would be wrong.
CACHE_DIR = Path.home() / ".claude" / "local" / "statusline"
CACHE_TTL_SECONDS = 24 * 3600  # PIDs are stable for the life of the session;
                               # a stale cache from a dead session is fine
                               # because PID lookups validate against /proc

# Process names we consider a "Claude Code root". Claude Code's
# canonical comm on this machine is "claude"; we accept variations
# for portability (claude-code on some installs, claude-cli, etc).
_CLAUDE_COMMS = frozenset({"claude", "claude-code", "claude-cli"})

# Safety bound on the walk — process tree depth in pathological cases.
# Typical depth is 4-6 (shell → tmux → terminal → kernel → init).
_MAX_WALK_DEPTH = 32


def _read_proc_comm(pid: int) -> Optional[str]:
    """Read /proc/<pid>/comm. Returns the stripped string or None.

    Never raises; the resolver tolerates dead-process races where the
    walk catches a pid that exits between stat lookups.
    """
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except (OSError, ValueError):
        return None


def _read_proc_ppid(pid: int) -> Optional[int]:
    """Read the parent pid from /proc/<pid>/stat.

    The /proc/<pid>/stat format is:
        <pid> (<comm>) <state> <ppid> ...
    where <comm> is in parens and may contain spaces / parens itself.
    Standard trick: find the LAST ')' and split fields after it.
    """
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except (OSError, ValueError):
        return None
    rparen = raw.rfind(")")
    if rparen < 0:
        return None
    fields = raw[rparen + 1:].split()
    if len(fields) < 2:
        return None
    try:
        return int(fields[1])  # field 4 of stat == fields[1] post-comm
    except ValueError:
        return None


def _walk_to_claude(start_pid: int) -> Optional[int]:
    """Walk parent-ward from `start_pid` until we hit a Claude Code root.

    Returns the matching pid, or None if the walk hits pid 1 / fails
    without finding a match.
    """
    pid = start_pid
    for _ in range(_MAX_WALK_DEPTH):
        if pid <= 1:
            return None
        comm = _read_proc_comm(pid)
        if comm is None:
            return None
        if comm in _CLAUDE_COMMS:
            return pid
        ppid = _read_proc_ppid(pid)
        if ppid is None or ppid == pid:
            return None
        pid = ppid
    return None


def _cache_path(session_id: str) -> Path:
    """One cache file per session — atomic-safe, never collides."""
    # Strip any non-hex chars defensively; session_ids are UUID hex.
    safe = "".join(c for c in session_id if c.isalnum() or c == "-")[:64]
    if not safe:
        safe = "anonymous"
    return CACHE_DIR / f"pid-cache-{safe}.json"


def _atomic_write_text(path: Path, content: str) -> None:
    """POSIX-atomic write — same pattern as persona_utils. Required
    because multiple concurrent statusline renders (tmux panes) can
    race on the same cache file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.rename(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def resolve(start_pid: int, session_id: str = "") -> int:
    """Resolve the stable Claude Code root PID for this session.

    1. If we have a session-keyed cache hit AND that pid still has comm
       in _CLAUDE_COMMS, return it (the session's claude process is
       still alive — re-using the cached resolution).
    2. Else walk up from `start_pid` looking for a Claude root.
    3. If found, persist to the cache and return it.
    4. Else fall back to `start_pid` (preserves v0.5.2 behavior on
       non-Claude-Code shells or when /proc is unavailable).

    `start_pid` should be os.getppid() at the call site. Passing it in
    rather than calling getppid() internally makes the function
    testable.
    """
    # Cache lookup with liveness check
    if session_id:
        cache_file = _cache_path(session_id)
        try:
            if cache_file.exists():
                stat = cache_file.stat()
                if time.time() - stat.st_mtime < CACHE_TTL_SECONDS:
                    cached = json.loads(cache_file.read_text())
                    cached_pid = cached.get("pid") if isinstance(cached, dict) else None
                    if isinstance(cached_pid, int) and cached_pid > 1:
                        # Liveness: the pid must still resolve to a claude root.
                        # If the original session died and the OS reused that
                        # pid for an unrelated process, we'd cache a wrong
                        # answer indefinitely. This check costs one /proc read.
                        comm = _read_proc_comm(cached_pid)
                        if comm in _CLAUDE_COMMS:
                            return cached_pid
        except (OSError, json.JSONDecodeError):
            pass  # corrupted cache → fall through to fresh walk

    # Fresh walk
    found = _walk_to_claude(start_pid)
    result = found if found is not None else start_pid

    # Persist (best-effort, atomic)
    if session_id and found is not None:
        try:
            _atomic_write_text(
                _cache_path(session_id),
                json.dumps({"pid": result, "session_id": session_id}),
            )
        except OSError:
            pass

    return result
