"""Per-session grid file I/O.

Each session gets its own grid file at /tmp/grid-{session_id}.json.
This isolates grids between concurrent sessions (multiple agents).

Pattern follows the existing identity cache at /tmp/statusline-sid-{session_id}.json.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from grid import Grid


def grid_path(session_id: str) -> Path:
    """Return the per-session grid file path."""
    return Path(f"/tmp/grid-{session_id}.json")


def load_grid(session_id: str) -> Grid:
    """Load grid from per-session file. Returns empty Grid on miss/error."""
    p = grid_path(session_id)
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return Grid.from_dict(data)
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        pass
    return Grid()


def save_grid(session_id: str, grid: Grid) -> None:
    """Atomically write grid to per-session file.

    Uses tempfile + rename for atomic writes (same pattern as state.py).
    """
    p = grid_path(session_id)
    data = json.dumps(grid.to_dict(), ensure_ascii=False)
    tmp = ""
    try:
        fd, tmp = tempfile.mkstemp(dir="/tmp", prefix=".grid_", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.rename(tmp, str(p))
    except Exception:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise
