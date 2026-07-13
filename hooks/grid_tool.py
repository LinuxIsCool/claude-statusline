#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "wcwidth>=0.2.0",
# ]
# ///
"""PreToolUse hook — append tool emoji to grid.

Reads hook stdin JSON: {session_id, tool_name, tool_input, ...}
Appends a tool-specific emoji to the per-session grid file.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Add lib/ to import path
LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))


def main() -> None:
    # Read hook stdin
    try:
        raw = sys.stdin.read()
        hook_data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, Exception):
        hook_data = {}

    session_id = hook_data.get("session_id", "")
    tool_name = hook_data.get("tool_name", "")

    if not session_id or not tool_name:
        return

    try:
        from grid import Cell
        from grid_io import load_grid, save_grid
        from grid_mapper import map_event, get_weight

        emoji, key = map_event("PreToolUse", tool_name=tool_name)
        weight = get_weight(key)
        grid = load_grid(session_id)
        grid.append(Cell(emoji=emoji, key=key, weight=weight, ts=time.time()))
        save_grid(session_id, grid)
    except Exception as e:
        sys.stderr.write(f"statusline: grid_tool: {e}\n")


if __name__ == "__main__":
    main()
