"""Tests for per-session grid file I/O."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from grid import Cell, Grid
from grid_io import grid_path, load_grid, save_grid


class TestGridPath:
    def test_returns_tmp_path(self):
        p = grid_path("abc-123")
        assert p == Path("/tmp/grid-abc-123.json")

    def test_different_sessions_different_paths(self):
        assert grid_path("aaa") != grid_path("bbb")


class TestSaveLoadRoundtrip:
    def test_save_and_load(self):
        sid = f"test-grid-io-{os.getpid()}"
        p = grid_path(sid)
        try:
            grid = Grid()
            grid.append(Cell("🌅", "event:session-start", 8, 1.0))
            grid.append(Cell("📖", "tool:read", 1, 2.0))
            save_grid(sid, grid)

            assert p.exists()
            loaded = load_grid(sid)
            assert loaded.cell_count() == 2
            assert loaded.rows[0][0].emoji == "🌅"
            assert loaded.rows[0][1].emoji == "📖"
        finally:
            p.unlink(missing_ok=True)

    def test_load_missing_returns_empty(self):
        grid = load_grid("nonexistent-session-id-xyz")
        assert grid.cell_count() == 0

    def test_load_corrupt_returns_empty(self):
        sid = f"test-grid-corrupt-{os.getpid()}"
        p = grid_path(sid)
        try:
            p.write_text("not json at all")
            grid = load_grid(sid)
            assert grid.cell_count() == 0
        finally:
            p.unlink(missing_ok=True)

    def test_save_overwrites(self):
        sid = f"test-grid-overwrite-{os.getpid()}"
        p = grid_path(sid)
        try:
            g1 = Grid()
            g1.append(Cell("🌅", "event:session-start", 8, 1.0))
            save_grid(sid, g1)

            g2 = Grid()
            g2.append(Cell("💬", "event:user-prompt", 10, 2.0))
            g2.append(Cell("📖", "tool:read", 1, 3.0))
            save_grid(sid, g2)

            loaded = load_grid(sid)
            assert loaded.cell_count() == 2
            assert loaded.rows[0][0].emoji == "💬"
        finally:
            p.unlink(missing_ok=True)
