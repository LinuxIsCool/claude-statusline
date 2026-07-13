#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "wcwidth>=0.2.0",
# ]
# ///
"""claude-statusline — main statusline command.

Reads Status payload from stdin, logs to JSONL + SQLite, renders via
the current theme, prints to stdout. This file is a thin orchestrator:
components.py COMPUTES data, themes.py FORMATS it, primitives.py provides
visual atoms. See also: cycle_theme.py for switching themes.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add lib/ to import path
LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from colors import get_palette
from components import compute_components
from logger import log_payload
from payload import StatusPayload
from state import load_state, detect_persona, save_state, load_config
from themes import get_theme, get_theme_by_name, THEME_REGISTRY


# ── Entry point ────────────────────────────────────────────────────

def main() -> None:
    """Read stdin, log, render, print."""
    # Read full stdin (Claude Code pipes JSON)
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""

    # Parse payload
    payload = StatusPayload.from_json(raw)

    # Load state + detect persona
    state = load_state()
    persona = detect_persona()

    # Override persona from payload agent_type if available
    # Format: "claude-personas:{slug}" — most reliable signal
    agent_type = payload.agent_type or ""
    if ":" in agent_type:
        slug_from_agent = agent_type.rsplit(":", 1)[-1].strip()
        if slug_from_agent:
            persona = slug_from_agent

    state["persona"] = persona

    session_id = payload.session_id or state.get("session_id", "")

    # Log payload (JSONL sync + SQLite async fork)
    try:
        if payload._raw:  # Only log if we got real data
            log_payload(payload, session_id, persona)
    except Exception as e:
        sys.stderr.write(f"statusline: status log_payload: {e}\n")

    # Load config (used for component toggles and default theme/color)
    config = load_config()

    # Resolve theme by name (primary) or legacy index (migration path)
    theme_name = state.get("theme")
    if theme_name:
        theme = get_theme_by_name(theme_name) or get_theme(0)
    else:
        # Legacy: migrate from theme_index → theme name
        theme_index = state.get("theme_index", 0)
        theme = get_theme(theme_index)
        state["theme"] = theme.name  # Migrate forward

    # Resolve color scheme — state overrides config default
    color_scheme = state.get("color_scheme")
    if not color_scheme:
        color_scheme = config.get("display", {}).get("default_color", theme.default_color_scheme)
        state["color_scheme"] = color_scheme
    palette = get_palette(color_scheme)

    # Filter disabled components before computing
    component_toggles = config.get("components", {})
    needed = theme.required_components()
    disabled = [c for c in needed if not component_toggles.get(c, True)]
    needed = [c for c in needed if component_toggles.get(c, True)]

    # If a theme-specific component was disabled, fall back to classic
    # (e.g. gpu theme with components.gpu: false → show classic instead)
    theme_specific = {"gpu"}  # Components that define a theme's identity
    if disabled and theme_specific & set(disabled):
        fallback = get_theme_by_name("classic")
        if fallback:
            theme = fallback
            needed = [c for c in theme.required_components() if component_toggles.get(c, True)]

    components = compute_components(needed, payload, state)

    # Render and print
    try:
        output = theme.render(components, palette)
        print(output, flush=True)
    except Exception as e:
        # Absolute fallback — always print something
        print(f"[{persona}] statusline error: {e}", flush=True)

    # Persist state updates (best-effort, CR-9: wrapped in try/except)
    try:
        save_state(state)
    except Exception as e:
        sys.stderr.write(f"statusline: status save_state: {e}\n")


if __name__ == "__main__":
    main()
