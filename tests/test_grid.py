"""Tests for the emoji memory grid data structure."""

import sys
from pathlib import Path

# Add lib/ to path so we can import grid
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from grid import Cell, Grid


class TestCell:
    def test_cell_creation(self):
        c = Cell(emoji="🌅", key="event:session-start", weight=8, ts=1000.0)
        assert c.emoji == "🌅"
        assert c.key == "event:session-start"
        assert c.weight == 8
        assert c.ts == 1000.0

    def test_cell_to_dict(self):
        c = Cell(emoji="🌅", key="event:session-start", weight=8, ts=1000.0)
        d = c.to_dict()
        assert d == {"emoji": "🌅", "key": "event:session-start", "weight": 8, "ts": 1000.0}

    def test_cell_from_dict(self):
        d = {"emoji": "💬", "key": "event:user-prompt-submit", "weight": 10, "ts": 2000.0}
        c = Cell.from_dict(d)
        assert c.emoji == "💬"
        assert c.weight == 10


class TestGridGrowth:
    def test_empty_grid(self):
        g = Grid()
        assert g.cell_count() == 0
        assert len(g.rows) == 0
        assert not g.is_full()

    def test_first_append_creates_row(self):
        g = Grid()
        g.append(Cell("🌅", "event:session-start", 8, 1.0))
        assert g.cell_count() == 1
        assert len(g.rows) == 1
        assert g.rows[0][0].emoji == "🌅"

    def test_append_same_row(self):
        g = Grid()
        g.append(Cell("🌅", "event:session-start", 8, 1.0))
        g.append(Cell("🔧", "event:pre-tool-use", 2, 2.0))
        assert g.cell_count() == 2
        assert len(g.rows) == 1

    def test_append_new_row(self):
        g = Grid()
        g.append(Cell("📖", "tool:read", 1, 1.0))
        g.append(Cell("💬", "event:user-prompt-submit", 10, 2.0))
        assert g.cell_count() == 2
        assert len(g.rows) == 2

    def test_row_overflow_creates_new_row(self):
        g = Grid(max_cols=3)
        g.append(Cell("🌅", "event:session-start", 8, 1.0))
        g.append(Cell("📖", "tool:read", 1, 2.0))
        g.append(Cell("📖", "tool:read", 1, 3.0))
        g.append(Cell("📖", "tool:read", 1, 4.0))
        assert len(g.rows) == 2
        assert len(g.rows[0]) == 3
        assert len(g.rows[1]) == 1

    def test_max_rows_respected(self):
        g = Grid(max_rows=2, max_cols=2)
        g.append(Cell("📖", "tool:read", 1, 1.0))
        g.append(Cell("📖", "tool:read", 1, 2.0))
        g.append(Cell("🚀", "event:subagent-start", 6, 3.0))
        g.append(Cell("📖", "tool:read", 1, 4.0))
        assert g.is_full()
        assert g.cell_count() == 4

    def test_new_row_when_max_rows_full_does_not_exceed(self):
        g = Grid(max_rows=2, max_cols=3)
        g.append(Cell("📖", "tool:read", 1, 1.0))
        g.append(Cell("💬", "event:user-prompt-submit", 10, 2.0))
        g.append(Cell("🚀", "event:subagent-start", 6, 3.0))
        assert len(g.rows) == 2  # Can't exceed max_rows


class TestGridEviction:
    def test_replacement_when_full(self):
        g = Grid(max_rows=2, max_cols=2)
        g.append(Cell("📖", "tool:read", 1, 1.0))
        g.append(Cell("📖", "tool:read", 1, 2.0))
        g.append(Cell("🚀", "event:subagent-start", 6, 3.0))
        g.append(Cell("📖", "tool:read", 1, 4.0))
        assert g.is_full()
        g.append(Cell("🐚", "tool:bash", 3, 5.0))
        assert g.cell_count() == 4
        assert len(g.rows) == 2

    def test_replaces_lightest_in_oldest_row(self):
        g = Grid(max_rows=1, max_cols=3)
        g.append(Cell("🌅", "event:session-start", 8, 1.0))
        g.append(Cell("📖", "tool:read", 1, 2.0))
        g.append(Cell("💬", "event:user-prompt-submit", 10, 3.0))
        assert g.is_full()
        g.append(Cell("🐚", "tool:bash", 3, 4.0))
        emojis = [c.emoji for c in g.rows[0]]
        assert emojis == ["🌅", "🐚", "💬"]

    def test_bookend_protection(self):
        g = Grid(max_rows=1, max_cols=3)
        g.append(Cell("🌅", "event:session-start", 8, 1.0))
        g.append(Cell("📖", "tool:read", 1, 2.0))
        g.append(Cell("📖", "tool:read", 1, 3.0))
        assert g.is_full()
        g.append(Cell("💬", "event:user-prompt-submit", 10, 4.0))
        assert g.rows[0][0].emoji == "🌅"

    def test_eviction_targets_oldest_row(self):
        g = Grid(max_rows=2, max_cols=2)
        g.append(Cell("📖", "tool:read", 1, 1.0))
        g.append(Cell("📖", "tool:read", 1, 2.0))
        g.append(Cell("🚀", "event:subagent-start", 6, 10.0))
        g.append(Cell("📖", "tool:read", 1, 11.0))
        assert g.is_full()
        g.append(Cell("🐚", "tool:bash", 3, 20.0))
        assert g.rows[0][1].emoji == "🐚"
        assert g.rows[0][1].ts == 20.0


class TestGridSerialization:
    def test_roundtrip_empty(self):
        g = Grid()
        d = g.to_dict()
        g2 = Grid.from_dict(d)
        assert g2.cell_count() == 0
        assert g2.max_rows == 10
        assert g2.max_cols == 10

    def test_roundtrip_with_cells(self):
        g = Grid()
        g.append(Cell("📖", "tool:read", 1, 1.0))
        g.append(Cell("💬", "event:user-prompt-submit", 10, 2.0))
        g.append(Cell("📖", "tool:read", 1, 3.0))
        d = g.to_dict()
        g2 = Grid.from_dict(d)
        assert g2.cell_count() == 3
        assert len(g2.rows) == 2
        assert g2.rows[0][0].emoji == "📖"
        assert g2.rows[1][0].emoji == "💬"
        assert g2.rows[1][1].emoji == "📖"

    def test_from_dict_handles_none(self):
        g = Grid.from_dict(None)
        assert g.cell_count() == 0

    def test_from_dict_handles_empty_dict(self):
        g = Grid.from_dict({})
        assert g.cell_count() == 0


class TestGridRowTimestamps:
    def test_row_timestamps(self):
        g = Grid()
        g.append(Cell("📖", "tool:read", 1, 100.0))
        g.append(Cell("📖", "tool:read", 1, 200.0))
        g.append(Cell("💬", "event:user-prompt-submit", 10, 300.0))
        ts = g.row_timestamps()
        assert ts[0] == 200.0
        assert ts[1] == 300.0


class TestGridCategoryRowBreaks:
    def test_same_category_appends_to_row(self):
        g = Grid()
        g.append(Cell("📖", "tool:read", 1, 1.0))
        g.append(Cell("🔎", "tool:grep", 1, 2.0))
        assert len(g.rows) == 1
        assert g.cell_count() == 2

    def test_user_prompt_after_tool_creates_new_row(self):
        g = Grid()
        g.append(Cell("📖", "tool:read", 1, 1.0))
        g.append(Cell("💬", "event:user-prompt-submit", 10, 2.0))
        assert len(g.rows) == 2

    def test_tool_after_user_prompt_same_row(self):
        g = Grid()
        g.append(Cell("💬", "event:user-prompt-submit", 10, 1.0))
        g.append(Cell("📖", "tool:read", 1, 2.0))
        assert len(g.rows) == 1

    def test_subagent_start_creates_new_row(self):
        g = Grid()
        g.append(Cell("📖", "tool:read", 1, 1.0))
        g.append(Cell("🚀", "event:subagent-start", 6, 2.0))
        assert len(g.rows) == 2

    def test_pre_compact_creates_new_row(self):
        g = Grid()
        g.append(Cell("📖", "tool:read", 1, 1.0))
        g.append(Cell("🗜️", "event:pre-compact", 6, 2.0))
        assert len(g.rows) == 2

    def test_session_start_creates_new_row(self):
        g = Grid()
        g.append(Cell("📖", "tool:read", 1, 1.0))
        g.append(Cell("🌅", "event:session-start", 8, 2.0))
        assert len(g.rows) == 2

    def test_event_after_event_same_row(self):
        g = Grid()
        g.append(Cell("🌅", "event:session-start", 8, 1.0))
        g.append(Cell("🔔", "event:notification", 2, 2.0))
        assert len(g.rows) == 1

    def test_row_overflow_still_works(self):
        g = Grid(max_cols=3)
        g.append(Cell("📖", "tool:read", 1, 1.0))
        g.append(Cell("📖", "tool:read", 1, 2.0))
        g.append(Cell("📖", "tool:read", 1, 3.0))
        g.append(Cell("📖", "tool:read", 1, 4.0))
        assert len(g.rows) == 2

    def test_first_cell_never_triggers_row_break(self):
        g = Grid()
        g.append(Cell("💬", "event:user-prompt-submit", 10, 1.0))
        assert len(g.rows) == 1
