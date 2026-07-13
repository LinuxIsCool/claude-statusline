"""State management for claude-statusline.

Atomic reads/writes via tempfile + os.rename. Persona detection from
environment or claude-personas plugin state.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, TypedDict


class SessionInfo(TypedDict, total=False):
    """Per-session metadata stored in state.json sessions dict."""
    persona: str
    session_number: int
    model: str
    started_at: str
    cost: float
    last_prompt: str


class StatusState(TypedDict, total=False):
    """Shape of state.json — the shared state between hooks and status.py."""
    theme: str
    color_scheme: str
    persona: str
    session_id: str
    session_number: int
    sessions: Dict[str, SessionInfo]
    topic_history: List[str]
    prompt_count: int
    memory_cache: Dict[str, Any]
    memory_refresh_counter: int
    session_title: str


STATE_PATH = Path.home() / ".claude" / "local" / "statusline" / "state.json"
LOCK_PATH = STATE_PATH.with_suffix(".lock")

PERSONAS_STATE_PATH = Path.home() / ".claude" / "local" / "personas" / "collective" / "agent-states.yaml"

DEFAULTS_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "defaults.yaml"
RUNTIME_CONFIG_PATH = Path.home() / ".claude" / "local" / "statusline" / "config.yaml"

DEFAULT_STATE: Dict[str, Any] = {
    "theme": "classic",           # Name-based (replaces legacy theme_index)
    "color_scheme": "catppuccin_mocha",
    "persona": "claude",
    "session_id": "",
    "session_number": 0,
    "sessions": {},
    "topic_history": [],
    "prompt_count": 0,
    "memory_cache": {},
}

# Keys that status.py actively computes during a Status event.
# Only these use the in-memory value in save_state(); everything else
# prefers the disk value to avoid clobbering concurrent writers.
STATUS_OWNED_KEYS: frozenset = frozenset({
    "topic_history", "prompt_count", "memory_cache",
    "memory_refresh_counter", "session_title",
    "persona", "session_number", "session_id",
})


def load_state() -> StatusState:
    """Load state from disk. Returns defaults if missing or corrupt.

    On fresh install (no state.json), seeds default theme and color from
    config/defaults.yaml so display.default_theme actually works.
    """
    try:
        if STATE_PATH.exists():
            text = STATE_PATH.read_text(encoding="utf-8")
            data = json.loads(text)
            if isinstance(data, dict):
                # Merge with defaults so new keys are always present
                merged = {**DEFAULT_STATE, **data}
                return merged
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        pass

    # Fresh install — seed from config defaults if available
    state = dict(DEFAULT_STATE)
    try:
        config = load_config()
        display = config.get("display", {})
        if "default_theme" in display:
            state["theme"] = display["default_theme"]
        if "default_color" in display:
            state["color_scheme"] = display["default_color"]
    except Exception:
        pass  # Expected on fresh install — no config.yaml yet
    return state


def save_state(state: StatusState) -> None:
    """Atomically write state under file lock.

    Uses the same LOCK_PATH as cycle_theme.py's merge_write() to prevent
    the lost-update race where status.py (running every ~300ms) could
    overwrite a theme switch made by cycle_theme.py.
    """
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_PATH, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # Re-read state under lock to merge any concurrent writes
        # (e.g. cycle_theme.py changed "theme" while we were computing)
        try:
            if STATE_PATH.exists():
                disk = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                if isinstance(disk, dict):
                    for key, val in disk.items():
                        if key in STATUS_OWNED_KEYS:
                            continue  # keep in-memory value
                        if key not in state:
                            state[key] = val
                        elif isinstance(val, dict) and isinstance(state.get(key), dict):
                            # Shallow merge: disk provides base, memory overlays
                            merged = {**val, **state[key]}
                            state[key] = merged
                        else:
                            # Scalar: prefer disk (preserves cycle_theme, session_start writes)
                            state[key] = val
        except (json.JSONDecodeError, OSError):
            pass  # If disk read fails, just write what we have

        # Write to temp file in same directory (same filesystem for atomic rename)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(STATE_PATH.parent),
            prefix=".state_",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.rename(tmp_path, str(STATE_PATH))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def detect_persona() -> str:
    """Detect the active persona slug.

    Priority:
      1. PERSONA_SLUG environment variable (set by claude-personas session-start hook)
      2. Falls back to "claude"

    Note: agent-states.yaml was previously used as step 2 but removed because
    it retains stale `status: active` indefinitely, causing background/headless
    sessions to inherit the last interactive persona. The PERSONA_SLUG env var
    is the correct signal — it's only set when a persona is explicitly activated.
    See: task-101 (statusline-persona-detection-stale-inheritance)
    """
    env_persona = os.environ.get("PERSONA_SLUG", "").strip()
    if env_persona:
        return env_persona
    return "claude"


def _parse_yaml_simple(text: str) -> Dict[str, Any]:
    """Minimal YAML parser for our controlled config format.

    Handles:
    - Up to 3 levels of nesting (indent 0 / indent 2 / indent 4+)
    - Scalar values: string, int, float, bool
    - Comments (lines starting with #) and empty lines
    - Inline comments after a space-hash

    Does NOT handle: lists, anchors, multi-line strings, or quoted
    strings with embedded colons.
    """
    result: Dict[str, Any] = {}
    # Stack tracks (indent_level, dict_ref) pairs so we can nest arbitrarily
    # within our practical 3-level limit.
    # current_path[0] = top-level section key, current_path[1] = sub-section key
    current_path: list[str] = []

    def _parse_scalar(raw: str) -> Any:
        """Convert a raw string value to the appropriate Python type."""
        v = raw.strip()
        # Boolean
        if v.lower() == "true":
            return True
        if v.lower() == "false":
            return False
        # Integer (no decimal point)
        try:
            if "." not in v:
                return int(v)
        except ValueError:
            pass
        # Float
        try:
            return float(v)
        except ValueError:
            pass
        # String — strip surrounding quotes if present
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            return v[1:-1]
        return v

    def _get_or_create_dict(path: list[str]) -> Dict[str, Any]:
        """Walk result dict along path, creating dicts as needed."""
        node: Dict[str, Any] = result
        for part in path:
            if part not in node or not isinstance(node[part], dict):
                node[part] = {}
            node = node[part]
        return node

    for line in text.splitlines():
        # Skip comments and blank lines
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if ":" not in stripped:
            continue

        # Detect indentation level (number of leading spaces)
        indent = len(line) - len(line.lstrip(" "))

        key_part, _, value_part = stripped.partition(":")
        key = key_part.strip()
        value_raw = value_part.strip()

        # Remove inline comment (only when '#' is preceded by whitespace)
        if " #" in value_raw:
            value_raw = value_raw[: value_raw.index(" #")].strip()

        is_section_header = value_raw == ""

        # Truncate current_path based on indent depth.
        # indent 0  → depth 0 (top-level)
        # indent 2  → depth 1 (one level under top-level section)
        # indent 4+ → depth 2 (one level under sub-section)
        depth = indent // 2
        current_path = current_path[:depth]

        if is_section_header:
            # Create dict at this depth and push key onto path
            parent = _get_or_create_dict(current_path)
            parent[key] = {}
            current_path.append(key)
        else:
            # Scalar leaf — attach to current nesting level
            parent = _get_or_create_dict(current_path)
            parent[key] = _parse_scalar(value_raw)

    return result


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge two dicts. Override wins for all leaf values."""
    merged: Dict[str, Any] = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config() -> Dict[str, Any]:
    """Load merged config: defaults.yaml + runtime config.yaml overrides."""
    defaults: Dict[str, Any] = {}
    if DEFAULTS_CONFIG_PATH.exists():
        defaults = _parse_yaml_simple(DEFAULTS_CONFIG_PATH.read_text(encoding="utf-8"))
    runtime: Dict[str, Any] = {}
    if RUNTIME_CONFIG_PATH.exists():
        runtime = _parse_yaml_simple(RUNTIME_CONFIG_PATH.read_text(encoding="utf-8"))
    return _deep_merge(defaults, runtime)
