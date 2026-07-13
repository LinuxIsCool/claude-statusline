"""Emoji memory grid — a fixed-capacity visual memory for session history.

Pure data structure. Zero I/O. Zero dependencies beyond stdlib.

The grid is a list of rows, each row a list of Cells. It grows until
max_rows * max_cols cells exist, then enters replacement mode.

Row breaks are determined automatically by category transitions:
- Forced break keys (session-start, subagent-start, pre-compact) always start a new row.
- event:user-prompt-submit after a tool:* cell starts a new row.
- Row overflow (max_cols reached) always starts a new row.
- Everything else appends to the current row.

Usage:
    grid = Grid()
    grid.append(Cell("🌅", "event:session-start", weight=8, ts=time.time()))
    grid.append(Cell("💬", "event:user-prompt-submit", weight=10, ts=time.time()))
    state["grid"] = grid.to_dict()
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Cell:
    """One emoji in the grid."""
    emoji: str       # The rendered glyph
    key: str         # emoji DB key (e.g., "tool:read", "event:stop")
    weight: int      # Eviction resistance: 1 (routine) to 10 (landmark)
    ts: float        # Unix timestamp when created

    def to_dict(self) -> dict:
        return {"emoji": self.emoji, "key": self.key, "weight": self.weight, "ts": self.ts}

    @classmethod
    def from_dict(cls, d: dict) -> Cell:
        return cls(
            emoji=d.get("emoji", "❓"),
            key=d.get("key", ""),
            weight=d.get("weight", 1),
            ts=d.get("ts", 0.0),
        )


@dataclass
class Grid:
    """10x10 emoji memory grid.

    Growth phase: append() adds cells. Row breaks are decided automatically
    based on category transitions between cells.
    Rows auto-wrap when max_cols is reached.
    When max_rows * max_cols cells exist, the grid is full.
    """
    rows: list[list[Cell]] = None  # type: ignore[assignment]
    max_rows: int = 10
    max_cols: int = 10

    _ROW_BREAK_KEYS: frozenset = frozenset({
        "event:session-start",
        "event:subagent-start",
        "event:pre-compact",
    })

    def __post_init__(self):
        if self.rows is None:
            self.rows = []

    def cell_count(self) -> int:
        """Total cells across all rows."""
        return sum(len(row) for row in self.rows)

    def is_full(self) -> bool:
        """True when cell_count >= max_rows * max_cols."""
        return self.cell_count() >= self.max_rows * self.max_cols

    def _should_new_row(self, current_row: list[Cell], new_cell: Cell) -> bool:
        new_key = new_cell.key

        if new_key in self._ROW_BREAK_KEYS:
            return True

        last_cell = current_row[-1] if current_row else None
        if not last_cell:
            return False
        last_cat = last_cell.key.split(":")[0] if ":" in last_cell.key else ""

        if new_key == "event:user-prompt-submit" and last_cat == "tool":
            return True

        return False

    def append(self, cell: Cell) -> None:
        """Add a cell to the grid.

        Row breaks are determined automatically by category transitions.
        If current row is full (max_cols), start a new row.
        If the grid is full, trigger replacement instead.
        """
        if self.is_full():
            self._replace(cell)
            return

        if not self.rows:
            self.rows.append([cell])
            return

        current_row = self.rows[-1]
        need_new_row = len(current_row) >= self.max_cols or self._should_new_row(current_row, cell)

        if need_new_row:
            if len(self.rows) < self.max_rows:
                self.rows.append([cell])
            else:
                if len(current_row) < self.max_cols:
                    current_row.append(cell)
                else:
                    self._replace(cell)
        else:
            current_row.append(cell)

    def _replace(self, cell: Cell) -> None:
        """Replace one existing cell using weight-based eviction.

        Targets the lightest non-bookend cell in the oldest row.
        Bookend protection: index 0 of each row is never evicted.
        """
        if not self.rows:
            return

        # Find the row with the oldest max-timestamp
        oldest_row_idx = 0
        oldest_ts = float("inf")
        for i, row in enumerate(self.rows):
            if not row:
                continue
            row_max_ts = max(c.ts for c in row)
            if row_max_ts < oldest_ts:
                oldest_ts = row_max_ts
                oldest_row_idx = i

        row = self.rows[oldest_row_idx]

        # Only one cell (the bookend) — replace it anyway
        if len(row) <= 1:
            row[0] = cell
            return

        # Find lightest cell, skipping bookend (index 0)
        lightest_idx = 1
        lightest_weight = row[1].weight
        for j in range(2, len(row)):
            if row[j].weight < lightest_weight:
                lightest_weight = row[j].weight
                lightest_idx = j

        row[lightest_idx] = cell

    def row_timestamps(self) -> list[float]:
        """Max timestamp per row."""
        return [max(c.ts for c in row) if row else 0.0 for row in self.rows]

    def to_dict(self) -> dict:
        """Serialize for state.json."""
        return {
            "max_rows": self.max_rows,
            "max_cols": self.max_cols,
            "rows": [[c.to_dict() for c in row] for row in self.rows],
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> Grid:
        """Deserialize from state.json."""
        if not data or not isinstance(data, dict):
            return cls()
        rows_data = data.get("rows", [])
        rows = []
        for row_data in rows_data:
            if isinstance(row_data, list):
                rows.append([Cell.from_dict(c) for c in row_data if isinstance(c, dict)])
        return cls(
            rows=rows,
            max_rows=data.get("max_rows", 10),
            max_cols=data.get("max_cols", 10),
        )
