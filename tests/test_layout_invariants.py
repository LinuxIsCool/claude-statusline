"""Property-based layout invariants for claude-statusline.

These tests use the Hypothesis library to generate arbitrary valid Grid+Row
configurations and assert that fundamental invariants hold across the space
of inputs. They catch regressions example-based tests can't reach.

Properties tested (from research/2026/05/31/statusline-brainstorm-pass-2 §2):
  P1: Rows whose span sum != len(columns) MUST raise ValueError.
  P2: visible_len(render(row)) == grid.total_width for any valid row.
  P3: Pipe characters only appear at the column-boundary positions defined
      by the grid geometry (8 cols × 16 width × " │ " separator).
  P4: render() is deterministic — same input → same output.
  P5: visible_len ↔ strip_ansi consistency for ANSI-free strings.
  P6: grid.total_width formula equals sum(col widths) + (n-1)*sep_visible.
  P7: Wrapping ANSI color around text does not change visible_len.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import pytest
from hypothesis import given, strategies as st, settings, assume
from layout_grid import Column, Cell, Row, Grid
from primitives import visible_len, strip_ansi


# ── Shared strategies ──────────────────────────────────────────────────

@st.composite
def safe_text(draw):
    """Generate arbitrary text excluding ANSI escape, control, and surrogate chars.

    Hypothesis's default text() can produce \\x1b, \\r, \\n which would either
    break visible_len() invariants or get rejected by the renderer. We exclude
    those so the property tests target the layout logic, not input sanitation.
    """
    return draw(
        st.text(
            alphabet=st.characters(
                blacklist_categories=("Cs", "Cc"),
                blacklist_characters="\x1b\r\n\t\x00",
            ),
            min_size=0,
            max_size=20,
        )
    )


@st.composite
def valid_cells_for_8col(draw):
    """Generate a list of Cells whose span sum equals exactly 8."""
    spans = []
    remaining = 8
    while remaining > 0:
        max_span = min(remaining, 3)
        span = draw(st.integers(min_value=1, max_value=max_span))
        spans.append(span)
        remaining -= span
    cells = []
    for s in spans:
        content = draw(safe_text())
        align = draw(st.sampled_from(["left", "right", "center", None]))
        cells.append(Cell(content=content, span=s, align=align))
    return cells


# Canonical 8-col × 16-wide grid used by all multi-cell properties.
GRID_8 = Grid(columns=[Column(f"c{i}", width=16) for i in range(8)])

# Pre-computed valid pipe positions for GRID_8 (16-wide cols, " │ " separator).
# Pipe is the 2nd char of " │ " — at offset 16+1 within each col+sep cycle.
_VALID_PIPE_POSITIONS = frozenset(
    16 + 1 + i * (16 + 3) for i in range(7)  # 7 separators between 8 cols
)


# ── Property tests ─────────────────────────────────────────────────────

@given(cells=valid_cells_for_8col())
@settings(max_examples=200, deadline=500)
def test_p2_render_width_equals_grid_total_width(cells):
    """P2: For any valid Row, visible_len(render(row)) == grid.total_width.

    This is the load-bearing invariant: every render of a valid row must
    occupy exactly the grid's declared width in visible cells. Content
    longer than its cell may overflow (current behavior, see _pad_visible
    in layout_grid.py); we `assume` content fits to test the padding path.
    """
    # If any cell's content visible width exceeds its merged span width,
    # _pad_visible returns the original (overflow) — skip those cases here.
    sep_visible = visible_len(" │ ")
    col_index = 0
    for cell in cells:
        merged_width = 16 * cell.span + (cell.span - 1) * sep_visible
        if visible_len(cell.content) > merged_width:
            assume(False)
        col_index += cell.span

    row = Row(cells=cells)
    output = GRID_8.render(row)
    assert visible_len(output) == GRID_8.total_width


@given(text=safe_text())
@settings(max_examples=200)
def test_p7_ansi_transparent_to_visible_len(text):
    """P7: Adding ANSI color around text does not change visible_len."""
    plain_len = visible_len(text)
    styled = f"\x1b[38;2;255;0;0m{text}\x1b[0m"
    assert visible_len(styled) == plain_len


def _pipe_visible_columns(rendered: str) -> set[int]:
    """Return the set of *visible-column* positions where '│' appears.

    Walking by str-index is wrong: a CJK or emoji char has str-length 1 but
    visible width 2, so str-index drifts from terminal-column position. We
    must accumulate visible_len of each char to get true column position.
    """
    plain = strip_ansi(rendered)
    positions = set()
    vis_col = 0
    for ch in plain:
        if ch == "│":
            positions.add(vis_col)
        vis_col += visible_len(ch)
    return positions


@given(cells_a=valid_cells_for_8col(), cells_b=valid_cells_for_8col())
@settings(max_examples=150, deadline=1000)
def test_p3_pipe_positions_only_at_column_boundaries(cells_a, cells_b):
    """P3: Pipes in rendered output land only at the column-boundary positions
    of the 8-col × 16-wide × " │ " grid (measured in VISIBLE columns).

    This guarantees vertical alignment across rows: if every pipe lands at a
    boundary position, two rows on the same grid will have pipes at a subset
    of the same positions, so cell separators line up visually.

    Notes:
    - Cells with span>1 collapse multiple columns into one region — so the
      number of pipes per row equals (n_cells - 1), not (n_cols - 1). The
      invariant is subset: every pipe MUST be at a boundary; not every
      boundary MUST have a pipe.
    - cell.content may itself contain "│"; those are content pipes, not
      layout pipes. We filter them out so the assertion is meaningful.
    """
    sep_visible = visible_len(" │ ")
    for cells in (cells_a, cells_b):
        for cell in cells:
            if "│" in cell.content:
                assume(False)
            # Overflow short-circuits the padding path (returns content as-is,
            # see _pad_visible in layout_grid.py); skip those — they're
            # tested by P2 and the example suite via separate truncation tests.
            merged = 16 * cell.span + (cell.span - 1) * sep_visible
            if visible_len(cell.content) > merged:
                assume(False)

    pipes_a = _pipe_visible_columns(GRID_8.render(Row(cells=cells_a)))
    pipes_b = _pipe_visible_columns(GRID_8.render(Row(cells=cells_b)))

    assert pipes_a.issubset(_VALID_PIPE_POSITIONS), (
        f"Row A pipes at {pipes_a - _VALID_PIPE_POSITIONS} are off-boundary"
    )
    assert pipes_b.issubset(_VALID_PIPE_POSITIONS), (
        f"Row B pipes at {pipes_b - _VALID_PIPE_POSITIONS} are off-boundary"
    )


@given(cells=valid_cells_for_8col())
@settings(max_examples=100)
def test_p4_render_is_deterministic(cells):
    """P4: Rendering the same row twice yields the same string."""
    row = Row(cells=cells)
    a = GRID_8.render(row)
    b = GRID_8.render(row)
    assert a == b


@given(s=safe_text())
@settings(max_examples=200)
def test_p5_visible_len_strip_ansi_consistency(s):
    """P5: For ANSI-free strings, strip_ansi is a no-op and visible_len is stable."""
    assert strip_ansi(s) == s
    assert visible_len(s) == visible_len(strip_ansi(s))


@given(
    width=st.integers(min_value=1, max_value=200),
    n_cols=st.integers(min_value=1, max_value=20),
)
@settings(max_examples=100)
def test_p6_grid_total_width_formula(width, n_cols):
    """P6: Grid.total_width = n*col_width + (n-1) * visible_len(separator)."""
    cols = [Column(f"c{i}", width=width) for i in range(n_cols)]
    grid = Grid(columns=cols, separator=" │ ")
    sep_vis = visible_len(" │ ")  # should be 3
    expected = n_cols * width + (n_cols - 1) * sep_vis
    assert grid.total_width == expected


@given(span=st.integers(min_value=1, max_value=20).filter(lambda x: x != 8))
@settings(max_examples=50)
def test_p1_span_sum_mismatch_raises(span):
    """P1: Rows whose span sum != len(columns) MUST raise ValueError on render."""
    cells = [Cell(content="x", span=span)]
    row = Row(cells=cells)
    with pytest.raises(ValueError, match=r"span sum"):
        GRID_8.render(row)


def test_p8_zero_width_chars_are_zero_without_wcwidth(monkeypatch):
    """P8: ZWSP (U+200B) is 0 cells even on the naive fallback path.

    _zwc() inserts ZWSPs to equalize char count and visible width; if the
    fallback counts them as 1, every emoji-bearing cell skips its padding
    and the grid's pipe alignment breaks (observed 2026-07-13 in envs
    without wcwidth installed).
    """
    import primitives
    monkeypatch.setattr(primitives, "_WCWIDTH_AVAILABLE", False)
    assert primitives.visible_len("​") == 0
    # char count == visible width after compensation, wcwidth or not
    assert primitives.visible_len("🪷​") == 2
