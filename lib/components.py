"""Component system for claude-statusline.

Components COMPUTE data from the StatusPayload and external sources.
Themes FORMAT that data for display. This separation keeps themes thin
and testable — they never touch raw payload fields directly.

Each component returns a ComponentData dict. Themes request specific
components by name; the registry computes only what's needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypedDict

from payload import StatusPayload


@dataclass
class ComponentData:
    """Output from a component computation."""
    name: str
    value: Dict[str, Any] = field(default_factory=dict)
    stale: bool = False
    error: Optional[str] = None


ComponentFn = Callable[[StatusPayload, dict], ComponentData]


# ── Component value TypedDicts ────────────────────────────────────────
# Each compute_* function returns a ComponentData whose .value dict
# matches one of these shapes. Type checkers verify key access in themes.


class IdentityValue(TypedDict, total=False):
    persona: str
    session_number: int
    agent_type: str
    session_name: str
    agent_name: str
    session_title: str
    session_id: str
    transcript_path: str
    # Shell-resolved fields (consolidated I/O — env + socket + getppid).
    # See compute_identity() for the resolution chain.
    host: str
    session_id_short: str  # 8-char prefix of the canonical session id
    pid: str               # ppid string or extracted from CLAUDEMATRIX_AGENT_ID
    persona_icon: str      # claude-emoji glyph for `persona:<slug>` (may be "")


class ContextValue(TypedDict):
    used_percentage: Optional[float]
    remaining_percentage: Optional[float]
    total_input_tokens: int
    total_output_tokens: int
    context_window_size: int
    exceeds_200k: bool


class CostValue(TypedDict):
    total_cost_usd: float
    total_duration_ms: int
    total_api_duration_ms: int
    burn_rate: float


class ModelValue(TypedDict):
    id: str
    display_name: str


class DurationValue(TypedDict):
    total_ms: int
    api_ms: int


class LinesValue(TypedDict):
    added: int
    removed: int


class VersionValue(TypedDict):
    version: str


class RateLimitsValue(TypedDict):
    five_hour_pct: float
    five_hour_resets: int
    seven_day_pct: float
    seven_day_resets: int


class CacheStatsValue(TypedDict):
    creation_tokens: int
    read_tokens: int


class WorktreeValue(TypedDict, total=False):
    active: bool
    name: str
    branch: str
    original_branch: str


class WorkspaceValue(TypedDict):
    cwd: str
    cwd_short: str
    project_dir: str
    output_style: str


class GitValue(TypedDict, total=False):
    is_repo: bool
    branch: str
    dirty: bool
    ahead: int
    behind: int


class TopicsValue(TypedDict):
    history: list
    current: str
    count: int


class SessionsValue(TypedDict):
    active: dict
    count: int


class GpuValue(TypedDict, total=False):
    available: bool
    name: str
    temp_c: int
    gpu_util: int
    mem_used_mib: int
    mem_total_mib: int
    power_w: float
    power_limit_w: float
    processes: list
    other_vram_mib: int  # VRAM used - sum(known process VRAM) — driver + uncounted


class CpuValue(TypedDict, total=False):
    available: bool
    name: str
    source: str        # "thermal-db" | "hwmon"
    chip: str          # "coretemp" | "k10temp"
    sensor: str        # "Package id 0" | "Tctl"
    temp_c: int
    high_c: int
    critical_c: int
    age_seconds: int
    cpu_pct: float
    ram_pct: float
    ram_used_mib: int
    ram_total_mib: int
    clock_mhz: int
    power_w: float
    power_limit_w: float
    power_available: bool
    fan_pct: int
    fan_available: bool
    processes: list


class PersonaValue(TypedDict, total=False):
    slug: str
    name: str
    role_slug: str
    role_name: str
    color: str
    model: str
    agency_level: int
    group: str
    tools_count: int
    knowledge_count: int
    backends_count: int


class MemoryValue(TypedDict):
    hippo: object
    koi: object
    journal: object
    letta: object
    messages: object
    files: object
    sessions: object
    total: object


class GridRowValue(TypedDict):
    timestamp: str
    emojis: list
    cell_count: int


class GridValue(TypedDict):
    rows: list
    total_cells: int
    is_full: bool


# ── Payload-sourced components (0ms — just extract from StatusPayload) ──


def _read_identity_cache(sid: str) -> Optional[Dict[str, Any]]:
    """Read file-based identity cache. Returns None on miss/error."""
    import json as _json
    cache_path = Path(f"/tmp/statusline-sid-{sid}.json")
    try:
        if cache_path.exists():
            data = _json.loads(cache_path.read_text())
            # Cache is valid forever — identity never changes mid-session
            return data
    except Exception as e:
        import sys as _sys
        _sys.stderr.write(f"statusline: _read_identity_cache({sid}): {e}\n")
    return None


def _write_identity_cache(sid: str, data: Dict[str, Any]) -> None:
    """Best-effort write to file-based identity cache."""
    import json as _json
    try:
        Path(f"/tmp/statusline-sid-{sid}.json").write_text(
            _json.dumps(data), encoding="utf-8"
        )
    except Exception as e:
        import sys as _sys
        _sys.stderr.write(f"statusline: _write_identity_cache({sid}): {e}\n")


def compute_identity(payload: StatusPayload, state: dict) -> ComponentData:
    """Persona, session number, agent type.

    Session number comes from SQLite (canonical source, set by session_start.py).
    Cached per-session in /tmp/statusline-sid-{session_id}.json since each
    `uv run` is a fresh process (module-level dicts are useless).
    Falls back to state.json sessions dict for backwards compatibility.
    """
    import sys as _sys

    sid = payload.session_id
    persona = state.get("persona", "claude")
    session_number = 0

    if not sid:
        # No session_id in payload — use state.json sessions dict
        # (shouldn't happen but guard against it)
        _sys.stderr.write("statusline: empty session_id in payload\n")
        session_number = state.get("session_number", 0)
    else:
        # 1. File-based cache (fast path — no SQLite on every render)
        cached = _read_identity_cache(sid)
        if cached:
            persona = cached.get("persona", persona)
            session_number = cached.get("session_number", 0)
        else:
            # 2. SQLite lookup + self-healing registration
            conn = None
            try:
                from db import get_connection, ensure_schema, lookup_session
                from db import next_session_number, upsert_session
                import time as _time
                conn = get_connection()
                ensure_schema(conn)
                row = lookup_session(conn, sid)
                if not row:
                    # session_start.py didn't fire — register now
                    num = next_session_number(conn, persona)
                    now_iso = _time.strftime("%Y-%m-%dT%H:%M:%S%z")
                    upsert_session(conn, session_id=sid, persona=persona,
                                   session_number=num, started_at=now_iso,
                                   last_seen=now_iso)
                    conn.execute("COMMIT")
                    row = {"persona": persona, "session_number": num}
                if row:
                    persona = row["persona"]
                    session_number = row["session_number"]
                    _write_identity_cache(sid, row)
            except Exception as e:
                _sys.stderr.write(f"statusline: compute_identity error: {e}\n")
            finally:
                if conn:
                    conn.close()

        # 3. Fallback: state.json sessions dict
        if not session_number:
            sessions = state.get("sessions", {})
            sess_data = sessions.get(sid, {})
            if sess_data:
                session_number = sess_data.get("session_number", 0)
                persona = sess_data.get("persona", persona)

        # 4. Last resort: top-level state.json (legacy single-session field)
        if not session_number:
            session_number = state.get("session_number", 0)

    # ── Shell-layer I/O: env vars + socket + getppid ──────────────────
    # All host/process/env reads consolidated here so theme renderers
    # stay pure functions of (components, palette) → string.
    import os as _os
    import socket as _socket

    # Persona override (env wins over state default if state didn't already
    # resolve a persona).
    if persona == "claude":
        env_persona = _os.environ.get("PERSONA_SLUG", "")
        if env_persona:
            persona = env_persona

    # Hostname — first DNS-style label, defensively defaulted.
    try:
        host = (_socket.gethostname() or "host").split(".")[0] or "host"
    except Exception:
        host = "host"

    # Session id resolution chain (mirrors the pre-refactor _row_identity
    # logic): CLAUDEMATRIX_SESSION_ID env → payload.session_id → basename of
    # transcript_path with .jsonl stripped → "".
    sid_full = _os.environ.get("CLAUDEMATRIX_SESSION_ID", "")
    if not sid_full:
        sid_full = payload.session_id or ""
    if not sid_full:
        tpath = payload.transcript_path or ""
        if tpath:
            base = tpath.rsplit("/", 1)[-1]
            if base.endswith(".jsonl"):
                base = base[:-6]
            sid_full = base
    sid_short = sid_full[:8] if sid_full else "????????"

    # PID resolution chain (task-552 Phase 2):
    #   1. Process-tree walk via pid_resolver.resolve() — find the nearest
    #      ancestor whose comm is "claude". Cached per session_id so the
    #      walk runs once per session, not every render. THIS IS PRIMARY
    #      because empirically it's the only source that always points at
    #      the actual claude CLI process — CLAUDEMATRIX_AGENT_ID encodes
    #      the matrix MCP server's PID instead, which is NOT the same
    #      process (matrix server is a child of claude). Walking gives us
    #      the parent we actually want shown in the identity row.
    #   2. CLAUDEMATRIX_AGENT_ID env (pid-<n>@<host>) — fallback for
    #      cases where /proc is unavailable or the walk doesn't find a
    #      claude ancestor (e.g., headless invocation outside a claude
    #      session entirely).
    #   3. os.getppid() — last-resort fallback (preserves v0.5.2 behavior).
    pid = ""
    try:
        raw_ppid = _os.getppid()
        from pid_resolver import resolve as _resolve_pid
        resolved = _resolve_pid(raw_ppid, session_id=sid_full)
        # resolve() returns start_pid unchanged when no claude ancestor
        # is found. We only trust the result if it actually moved (a
        # claude was found) — otherwise fall through to env / getppid.
        if resolved != raw_ppid:
            pid = str(resolved)
    except Exception:
        pass

    if not pid:
        agent_id = _os.environ.get("CLAUDEMATRIX_AGENT_ID", "")
        if agent_id.startswith("pid-"):
            tail = agent_id[4:]
            pid_candidate = tail.split("@", 1)[0] if "@" in tail else tail
            if pid_candidate.isdigit():
                pid = pid_candidate

    if not pid:
        try:
            pid = str(_os.getppid())
        except Exception:
            pid = "?"

    # Persona signature glyph from claude-emoji DB. Routed through
    # get_persona_info so it rides the existing /tmp cache (5-min TTL)
    # rather than re-opening sqlite on every render. Empty string when DB
    # unreachable or slug unmapped — renderer falls back to "🪷".
    try:
        from persona_utils import get_persona_info
        persona_icon = get_persona_info(persona).get("icon", "")
    except Exception:
        persona_icon = ""

    return ComponentData(
        name="identity",
        value={
            "persona": persona,
            "session_number": session_number,
            "agent_type": payload.agent_type,
            "session_name": payload.session_name,
            "agent_name": payload.agent.name if payload.agent else "",
            "session_title": state.get("session_title", ""),
            "session_id": payload.session_id or "",
            "transcript_path": payload.transcript_path or "",
            # Shell-resolved fields.
            "host": host,
            "session_id_short": sid_short,
            "pid": pid,
            "persona_icon": persona_icon,
        },
    )


def compute_context(payload: StatusPayload, state: dict) -> ComponentData:
    """Context window usage."""
    cw = payload.context_window
    return ComponentData(
        name="context",
        value={
            "used_percentage": cw.used_percentage,
            "remaining_percentage": cw.remaining_percentage,
            "total_input_tokens": cw.total_input_tokens,
            "total_output_tokens": cw.total_output_tokens,
            "context_window_size": cw.context_window_size,
            "exceeds_200k": payload.exceeds_200k_tokens,
        },
    )


def compute_cost(payload: StatusPayload, state: dict) -> ComponentData:
    """Cost and duration."""
    c = payload.cost
    return ComponentData(
        name="cost",
        value={
            "total_cost_usd": c.total_cost_usd,
            "total_duration_ms": c.total_duration_ms,
            "total_api_duration_ms": c.total_api_duration_ms,
            # Burn rate: $/hr
            "burn_rate": (c.total_cost_usd / (c.total_duration_ms / 3_600_000))
            if c.total_duration_ms > 0
            else 0.0,
        },
    )


def compute_model(payload: StatusPayload, state: dict) -> ComponentData:
    """Model info."""
    return ComponentData(
        name="model",
        value={
            "id": payload.model.id,
            "display_name": payload.model.display_name,
        },
    )


def compute_duration(payload: StatusPayload, state: dict) -> ComponentData:
    """Session duration."""
    return ComponentData(
        name="duration",
        value={
            "total_ms": payload.cost.total_duration_ms,
            "api_ms": payload.cost.total_api_duration_ms,
        },
    )


def compute_lines(payload: StatusPayload, state: dict) -> ComponentData:
    """Lines added/removed."""
    return ComponentData(
        name="lines",
        value={
            "added": payload.cost.total_lines_added,
            "removed": payload.cost.total_lines_removed,
        },
    )


def compute_version(payload: StatusPayload, state: dict) -> ComponentData:
    """Claude Code version."""
    return ComponentData(
        name="version",
        value={"version": payload.version},
    )


def compute_rate_limits(payload: StatusPayload, state: dict) -> ComponentData:
    """Rate limit percentages."""
    if not payload.rate_limits:
        return ComponentData(name="rate_limits", value={
            "five_hour_pct": 0.0,
            "five_hour_resets": 0,
            "seven_day_pct": 0.0,
            "seven_day_resets": 0,
        })
    return ComponentData(
        name="rate_limits",
        value={
            "five_hour_pct": payload.rate_limits.five_hour.used_percentage,
            "five_hour_resets": payload.rate_limits.five_hour.resets_at,
            "seven_day_pct": payload.rate_limits.seven_day.used_percentage,
            "seven_day_resets": payload.rate_limits.seven_day.resets_at,
        },
    )


def compute_cache_stats(payload: StatusPayload, state: dict) -> ComponentData:
    """Cache creation and read token counts."""
    cu = payload.context_window.current_usage
    return ComponentData(
        name="cache_stats",
        value={
            "creation_tokens": cu.cache_creation_input_tokens,
            "read_tokens": cu.cache_read_input_tokens,
        },
    )


def compute_worktree(payload: StatusPayload, state: dict) -> ComponentData:
    """Worktree info if active."""
    if not payload.worktree:
        return ComponentData(name="worktree", value={"active": False})
    return ComponentData(
        name="worktree",
        value={
            "active": True,
            "name": payload.worktree.name,
            "branch": payload.worktree.branch,
            "original_branch": payload.worktree.original_branch,
        },
    )


def compute_workspace(payload: StatusPayload, state: dict) -> ComponentData:
    """Workspace path info."""
    cwd = payload.workspace.current_dir or payload.cwd or "?"
    home = str(Path.home())
    if cwd.startswith(home):
        cwd_short = "~" + cwd[len(home):]
    else:
        cwd_short = cwd
    return ComponentData(
        name="workspace",
        value={
            "cwd": payload.workspace.current_dir or payload.cwd or "?",
            "cwd_short": cwd_short,
            "project_dir": payload.workspace.project_dir,
            "output_style": payload.output_style,
        },
    )


# ── External-sourced components (cached, refreshed periodically) ──────


def compute_git(payload: StatusPayload, state: dict) -> ComponentData:
    """Git branch, dirty, ahead/behind. Cached 10s via git_utils."""
    try:
        from git_utils import get_git_info
        cwd = payload.workspace.current_dir or payload.cwd
        info = get_git_info(cwd) if cwd else {"is_repo": False}
        return ComponentData(name="git", value=info)
    except Exception as e:
        return ComponentData(name="git", value={"is_repo": False}, error=str(e))


def compute_topics(payload: StatusPayload, state: dict) -> ComponentData:
    """Topic history from state.json."""
    history = state.get("topic_history", [])
    return ComponentData(
        name="topics",
        value={
            "history": history[-10:],  # Last 10 topics
            "current": history[-1] if history else "",
            "count": len(history),
        },
    )


def compute_sessions(payload: StatusPayload, state: dict) -> ComponentData:
    """Active sessions from state.json."""
    sessions = state.get("sessions", {})
    return ComponentData(
        name="sessions",
        value={
            "active": sessions,
            "count": len(sessions),
        },
    )


def compute_gpu(payload: StatusPayload, state: dict) -> ComponentData:
    """GPU metrics via nvidia-smi. Cached 3s in /tmp."""
    try:
        from gpu_utils import get_gpu_info
        info = get_gpu_info()
        return ComponentData(name="gpu", value=info)
    except Exception as e:
        return ComponentData(name="gpu", value={"available": False}, error=str(e))


def compute_cpu(payload: StatusPayload, state: dict) -> ComponentData:
    """CPU package temp via claude-thermal DB or hwmon scan. Cached 3s in /tmp."""
    try:
        from cpu_utils import get_cpu_info
        info = get_cpu_info()
        return ComponentData(name="cpu", value=info)
    except Exception as e:
        return ComponentData(name="cpu", value={"available": False}, error=str(e))


def compute_turn(payload: StatusPayload, state: dict) -> ComponentData:
    """Current-response duration by tailing the transcript JSONL.

    Returns {duration_ms, is_active}. is_active=True when the assistant is
    still streaming (no completed assistant message after the last user one).
    Cached for ~1s via a /tmp file to avoid re-tailing on every render.
    """
    import json as _json
    import time as _time
    from datetime import datetime, timezone
    from pathlib import Path as _Path

    cache_file = _Path("/tmp/statusline-turn.json")
    transcript = payload.transcript_path or ""

    # If transcript_path is empty, return zero immediately — no work to do,
    # and the cache (keyed only by time) would return a stale value from a
    # different transcript_path otherwise.
    if not transcript:
        return ComponentData(name="turn", value={"duration_ms": 0, "is_active": False})

    # 1s cache (only valid when we have a transcript to potentially re-read).
    try:
        if cache_file.exists() and (_time.time() - cache_file.stat().st_mtime) < 1.0:
            cached = _json.loads(cache_file.read_text())
            return ComponentData(name="turn", value=cached)
    except (OSError, _json.JSONDecodeError):
        pass

    result = {"duration_ms": 0, "is_active": False}

    if transcript:
        p = _Path(transcript)
        if p.exists():
            try:
                size = p.stat().st_size
                with p.open("rb") as f:
                    f.seek(max(0, size - 65536))
                    tail = f.read().decode("utf-8", errors="replace")
                last_user_ts = None
                last_assistant_ts = None
                for line in tail.splitlines()[-300:]:
                    line = line.strip()
                    if not line.startswith("{"):
                        continue
                    try:
                        obj = _json.loads(line)
                    except _json.JSONDecodeError:
                        continue
                    ts_str = obj.get("timestamp")
                    if not ts_str:
                        continue
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    type_ = obj.get("type")
                    if type_ == "user":
                        last_user_ts = ts
                    elif type_ == "assistant":
                        last_assistant_ts = ts
                if last_user_ts is not None:
                    if last_assistant_ts and last_assistant_ts > last_user_ts:
                        result["duration_ms"] = int((last_assistant_ts - last_user_ts).total_seconds() * 1000)
                        result["is_active"] = False
                    else:
                        result["duration_ms"] = int((datetime.now(timezone.utc) - last_user_ts).total_seconds() * 1000)
                        result["is_active"] = True
            except OSError:
                pass

    try:
        cache_file.write_text(_json.dumps(result))
    except OSError:
        pass
    return ComponentData(name="turn", value=result)


def compute_net(payload: StatusPayload, state: dict) -> ComponentData:
    """Networking metrics: iface, rates, signal, Tailscale peers, WireGuard tunnels."""
    try:
        from net_utils import get_net_info
        info = get_net_info()
        return ComponentData(name="net", value=info)
    except Exception as e:
        return ComponentData(name="net", value={"available": False}, error=str(e))


def compute_persona(payload: StatusPayload, state: dict) -> ComponentData:
    """Persona identity from claude-personas character/role YAML. Cached 5min in /tmp."""
    slug = state.get("persona", "claude")
    try:
        from persona_utils import get_persona_info
        info = get_persona_info(slug)
        return ComponentData(name="persona", value=info)
    except Exception as e:
        return ComponentData(name="persona", value={"slug": slug, "color": ""}, error=str(e))


def compute_memory(payload: StatusPayload, state: dict) -> ComponentData:
    """Memory backend counts. Reads from cache, refreshes one backend every ~18s.

    Cache is populated on session start (fork). During Status events,
    every 60th call (~18s at 300ms interval) refreshes one backend
    round-robin to keep values fresh without blocking render.

    Side effects: mutates state["memory_cache"] and state["memory_refresh_counter"].
    These mutations are persisted by status.py which calls save_state(state) after
    compute_components() returns. Never call this function if you don't intend to
    save state — the counter will advance without the cache being persisted.
    """
    cache = state.get("memory_cache", {})
    counter = state.get("memory_refresh_counter", 0)

    # Every 60 status events, refresh one backend (round-robin)
    if counter > 0 and counter % 60 == 0:
        try:
            from memory import BACKENDS
            backend_idx = (counter // 60) % len(BACKENDS)
            name, query_fn = BACKENDS[backend_idx]
            cache[name] = query_fn()
            # Recompute total from all integer values
            int_vals = [v for v in cache.values() if isinstance(v, int)]
            cache["total"] = sum(int_vals) if int_vals else cache.get("total", "?")
            state["memory_cache"] = cache
        except Exception as e:
            import sys as _sys
            _sys.stderr.write(f"statusline: compute_memory refresh: {e}\n")

    state["memory_refresh_counter"] = counter + 1

    return ComponentData(
        name="memory",
        value={
            "hippo": cache.get("hippo", "?"),
            "koi": cache.get("koi", "?"),
            "journal": cache.get("journal", "?"),
            "letta": cache.get("letta", "?"),
            "messages": cache.get("messages", "?"),
            "files": cache.get("files", "?"),
            "sessions": cache.get("sessions", "?"),
            "total": cache.get("total", "?"),
        },
        stale=counter % 60 != 0,
    )


def compute_grid(payload: StatusPayload, state: dict) -> ComponentData:
    """Grid state from per-session file, formatted for theme consumption."""
    import time as _time

    try:
        from grid_io import load_grid
    except ImportError:
        return ComponentData(name="grid", value={"rows": [], "total_cells": 0, "is_full": False})

    sid = payload.session_id
    if not sid:
        return ComponentData(name="grid", value={"rows": [], "total_cells": 0, "is_full": False})

    grid = load_grid(sid)

    rows = []
    for row in grid.rows:
        if not row:
            continue
        max_ts = max(c.ts for c in row)
        rows.append({
            "timestamp": _time.strftime("%H:%M", _time.localtime(max_ts)),
            "emojis": [c.emoji for c in row],
            "cell_count": len(row),
        })

    return ComponentData(
        name="grid",
        value={
            "rows": rows,
            "total_cells": grid.cell_count(),
            "is_full": grid.is_full(),
        },
    )


# ── Registry ─────────────────────────────────────────────────────────

COMPONENT_REGISTRY: Dict[str, ComponentFn] = {
    "identity": compute_identity,
    "context": compute_context,
    "cost": compute_cost,
    "model": compute_model,
    "duration": compute_duration,
    "lines": compute_lines,
    "version": compute_version,
    "rate_limits": compute_rate_limits,
    "cache_stats": compute_cache_stats,
    "worktree": compute_worktree,
    "workspace": compute_workspace,
    "git": compute_git,
    "topics": compute_topics,
    "sessions": compute_sessions,
    "memory": compute_memory,
    "gpu": compute_gpu,
    "cpu": compute_cpu,
    "turn": compute_turn,
    "net": compute_net,
    "persona": compute_persona,
    "grid": compute_grid,
}


def compute_components(
    needed: List[str],
    payload: StatusPayload,
    state: dict,
) -> Dict[str, ComponentData]:
    """Compute only the components a theme needs."""
    result = {}
    for name in needed:
        fn = COMPONENT_REGISTRY.get(name)
        if fn:
            try:
                result[name] = fn(payload, state)
            except Exception as e:
                result[name] = ComponentData(name=name, error=str(e))
        else:
            result[name] = ComponentData(name=name, error=f"unknown component: {name}")
    return result
