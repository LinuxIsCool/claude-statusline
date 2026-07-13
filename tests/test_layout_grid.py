"""Tests for the lib/layout_grid.py declarative colspan grid primitives."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import pytest
from layout_grid import Column, Cell, Row, Grid


def test_column_has_name_width_align():
    c = Column(name="temp", width=8, align="center")
    assert c.name == "temp"
    assert c.width == 8
    assert c.align == "center"


def test_column_align_defaults_to_left():
    c = Column(name="proc", width=22)
    assert c.align == "left"


def test_cell_has_content_span_align_flex():
    c = Cell(content="hello", span=2, align="right", flex=True)
    assert c.content == "hello"
    assert c.span == 2
    assert c.align == "right"
    assert c.flex is True


def test_cell_defaults():
    c = Cell(content="x")
    assert c.span == 1
    assert c.align is None
    assert c.flex is False


def test_row_holds_cells_and_align_default():
    r = Row(cells=[Cell("a"), Cell("b")], align="center")
    assert len(r.cells) == 2
    assert r.align == "center"


def test_row_align_defaults_to_none():
    r = Row(cells=[Cell("a")])
    assert r.align is None


def test_grid_total_width_sums_columns_plus_separators():
    cols = [Column("a", 10), Column("b", 5), Column("c", 7)]
    g = Grid(columns=cols, separator=" │ ")
    # 10 + 5 + 7 = 22 content + 2 separators * 3 visible chars = 22 + 6 = 28
    assert g.total_width == 28


def test_grid_separator_default():
    g = Grid(columns=[Column("x", 10)])
    assert g.separator == " │ "


def test_grid_render_rejects_invalid_span_sum():
    g = Grid(columns=[Column("a", 5), Column("b", 5)])  # 2 cols
    bad_row = Row(cells=[Cell("hi", span=3)])  # span 3 but only 2 cols
    with pytest.raises(ValueError, match="span sum"):
        g.render(bad_row)


def test_grid_render_accepts_matching_span_sum():
    g = Grid(columns=[Column("a", 5), Column("b", 5)])
    row = Row(cells=[Cell("hi"), Cell("yo")])  # span 1+1 = 2 ✓
    output = g.render(row)
    assert "hi" in output
    assert "yo" in output


def test_grid_render_single_cell_left_aligned():
    g = Grid(columns=[Column("a", 10, align="left")])
    row = Row(cells=[Cell("hi")])
    output = g.render(row)
    # "hi" + 8 spaces of padding
    assert output == "hi        "


def test_grid_render_single_cell_right_aligned():
    g = Grid(columns=[Column("a", 10, align="right")])
    row = Row(cells=[Cell("hi")])
    output = g.render(row)
    assert output == "        hi"


def test_grid_render_single_cell_center_aligned():
    g = Grid(columns=[Column("a", 10, align="center")])
    row = Row(cells=[Cell("hi")])
    output = g.render(row)
    # 4 spaces, "hi", 4 spaces
    assert output == "    hi    "


def test_grid_render_two_cells_joined_with_separator():
    g = Grid(columns=[Column("a", 4), Column("b", 4)], separator=" │ ")
    row = Row(cells=[Cell("ab"), Cell("cd")])
    output = g.render(row)
    # "ab  " + " │ " + "cd  " = "ab   │ cd  "
    assert output == "ab   │ cd  "


def test_visible_len_handles_double_width_emoji():
    """🪷 lotus emoji should count as 2 visible cells, not 1."""
    from primitives import visible_len
    assert visible_len("🪷") == 2


def test_visible_len_handles_emoji_with_variation_selector():
    """🖥️ (computer + U+FE0F) should count as 2 cells."""
    from primitives import visible_len
    assert visible_len("🖥️") == 2


def test_visible_len_strips_ansi_escapes():
    from primitives import visible_len
    assert visible_len("\x1b[31mhello\x1b[0m") == 5


def test_grid_emoji_pads_correctly():
    """A cell with a 🪷 emoji (visible width 2) plus 'matt' (4) totals 6;
    padding should fill to col width = 10, leaving 4 spaces of trailing pad."""
    cols = [Column("a", 10, align="left")]
    g = Grid(columns=cols)
    row = Row(cells=[Cell("🪷 matt")])
    rendered = g.render(row)
    from primitives import visible_len
    assert visible_len(rendered) == 10


def test_grid_row_factory_validates_span_sum():
    """Grid.row() raises ValueError immediately for malformed cells."""
    g = Grid(columns=[Column("a", 10), Column("b", 10)])
    # Valid construction
    row = g.row(cells=[Cell("x"), Cell("y")])
    assert isinstance(row, Row)
    # Invalid: span sum > columns
    with pytest.raises(ValueError, match="span sum"):
        g.row(cells=[Cell("x", span=2), Cell("y", span=2)])
    # Invalid: span sum < columns
    with pytest.raises(ValueError, match="span sum"):
        g.row(cells=[Cell("x")])


def test_grid_row_factory_accepts_valid_spans():
    """Grid.row() accepts all valid span combinations."""
    g = Grid(columns=[Column(f"c{i}", 10) for i in range(4)])
    # span=4 single cell
    g.row(cells=[Cell("x", span=4)])
    # span=2 + span=2
    g.row(cells=[Cell("x", span=2), Cell("y", span=2)])
    # 4 span=1
    g.row(cells=[Cell("a"), Cell("b"), Cell("c"), Cell("d")])
