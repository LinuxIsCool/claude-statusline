"""Declarative colspan grid for claude-statusline GpuTheme.

Layout is data, not code. Define COLUMNS once; each Row is a list of Cells
that span integer numbers of columns. The renderer guarantees that every `│`
character lands on a fixed column boundary, so pipes vertically align across
rows by construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class Column:
    """A grid column with a fixed visible width and default alignment.

    align: "left" | "center" | "right". This is the lowest-priority default;
    Row.align and Cell.align override it (cell wins over row wins over column).
    """
    name: str
    width: int
    align: str = "left"


@dataclass(frozen=True)
class Cell:
    """A grid cell.

    span:   number of adjacent columns this cell occupies (>=1).
    align:  if set, overrides Row.align and Column.align for this cell only.
    flex:   if True AND this cell is the LAST present cell on its row, expand
            its span to consume all trailing columns. Use for path-style cells.
    """
    content: str
    span: int = 1
    align: Optional[str] = None
    flex: bool = False


@dataclass(frozen=True)
class Row:
    """A row of cells, optionally with a row-level alignment default."""
    cells: List[Cell]
    align: Optional[str] = None


@dataclass(frozen=True)
class Grid:
    """Renders Rows of Cells into a single visible-width-correct string.

    Algorithm:
      1. Validate sum of cell.span equals len(columns)
      2. Apply Cell.flex: if last present cell has flex=True and total span < N,
         extend its span to consume trailing columns.
      3. For each cell, compute its merged width = sum(col widths spanned)
         + (span-1) * len(separator).
      4. Pad cell content to merged width with alignment resolution:
         cell.align ?? row.align ?? column.align ?? "left"
      5. Join cells with separator.
    """

    columns: List[Column]
    separator: str = " │ "

    @property
    def total_width(self) -> int:
        """Visible width of any rendered row (content + separators)."""
        sep_visible = _visible_len(self.separator)
        return sum(c.width for c in self.columns) + (len(self.columns) - 1) * sep_visible

    def row(self, cells: List[Cell], align: Optional[str] = None) -> Row:
        """Construct a Row, validating span sum at construction time.

        Raises ValueError immediately if cell spans don't sum to len(columns).
        This catches layout bugs at the line that creates the row, not later
        at render time. Preferred over `Row(cells=...)` direct construction.
        """
        span_sum = sum(c.span for c in cells)
        if span_sum != len(self.columns):
            raise ValueError(
                f"Row span sum ({span_sum}) does not equal number of "
                f"columns ({len(self.columns)}). Cells: {cells!r}"
            )
        return Row(cells=cells, align=align)

    def render(self, row: Row) -> str:
        cells = self._apply_flex(row.cells)
        span_sum = sum(c.span for c in cells)
        if span_sum != len(self.columns):
            raise ValueError(
                f"Row span sum ({span_sum}) does not equal number of "
                f"columns ({len(self.columns)})"
            )

        sep_visible = _visible_len(self.separator)
        rendered_cells: List[str] = []
        col_index = 0
        for cell in cells:
            spanned_cols = self.columns[col_index : col_index + cell.span]
            merged_width = (
                sum(c.width for c in spanned_cols) + (cell.span - 1) * sep_visible
            )
            align = (
                cell.align
                or row.align
                or spanned_cols[0].align
                or "left"
            )
            rendered_cells.append(_pad_visible(cell.content, merged_width, align))
            col_index += cell.span

        return self.separator.join(rendered_cells)

    @staticmethod
    def _apply_flex(cells: List[Cell]) -> List[Cell]:
        """If the LAST cell has flex=True, return cells unchanged — flex only
        matters when there are FEWER cells than columns (handled by callers
        composing rows). For now this is a passthrough; Task 9 wires up real
        flex semantics via _pack_workspace_row()."""
        return list(cells)


# ── Visible-width helpers ──────────────────────────────────────────────

import re as _re

from primitives import (  # noqa: E402
    visible_len as _visible_len,
    strip_ansi as _strip_ansi,
    _truncate_visible,
)

# Consecutive ANSI SGR codes at the very start of a styled cell (the cell's
# leading colour), so a truncated cell keeps its colour instead of going plain.
_LEADING_ANSI = _re.compile(r"^(?:\x1b\[[0-9;]*m)+")


def _truncate_styled(s: str, target_width: int) -> str:
    """Clip a (possibly ANSI-styled) string to EXACTLY `target_width` visible
    cells, ending in '…'. Preserves the cell's leading colour (and resets after)
    so the grid's fixed-width contract holds even when content overflows —
    honouring the module's "every │ lands on a fixed column boundary" promise.
    """
    if target_width <= 0:
        return ""
    ellipsis = "…"
    plain = _strip_ansi(s)
    clipped = _truncate_visible(plain, target_width - _visible_len(ellipsis)) + ellipsis
    # A wide-char boundary can leave us one cell short; pad to the exact width.
    short = target_width - _visible_len(clipped)
    if short > 0:
        clipped += " " * short
    lead = _LEADING_ANSI.match(s)
    return (lead.group(0) + clipped + "\x1b[0m") if lead else clipped


def _pad_visible(s: str, target_width: int, align: str = "left") -> str:
    """Pad `s` to `target_width` visible chars; truncate with '…' if longer."""
    vlen = _visible_len(s)
    if vlen > target_width:
        # Enforce the grid's fixed-width contract: an overflowing cell would
        # push every downstream '│' right and break vertical alignment.
        return _truncate_styled(s, target_width)
    pad = " " * (target_width - vlen)
    if align == "right":
        return pad + s
    if align == "center":
        left = (target_width - vlen) // 2
        right = (target_width - vlen) - left
        return (" " * left) + s + (" " * right)
    return s + pad
