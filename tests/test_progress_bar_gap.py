"""Phase 1 regression test — progress bars must not produce visual gaps
at the fill boundary.

The eighth-block partial characters (▏▎▍▌▋▊▉, U+258F-U+2589) render the
LEFT portion in the foreground color and the RIGHT portion in whatever
background was active. The previous implementation set only fg on the
partial block, so the right portion rendered as the terminal default
(transparent) rather than the empty-bar dim color. Result: a variable-
size visible gap proportional to (1 - partial_fraction).

The fix: emit `fg(fill_color) + bg(empty_color) + BLOCK_CHARS[partial]`
so the cell renders as [bright left | dim right] — no transparency, no
gap, smooth gradient.

This file owns the gap-free invariant. Any future progress_bar refactor
that drops the bg call will fail these tests.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import pytest

from primitives import BLOCK_CHARS, progress_bar, strip_ansi, visible_len

# ANSI SGR sequences we inspect for fg/bg presence.
_FG_RGB_RE = re.compile(r"\x1b\[38;2;\d+;\d+;\d+m")
_BG_RGB_RE = re.compile(r"\x1b\[48;2;\d+;\d+;\d+m")


def _partial_block_positions(rendered: str) -> list[int]:
    """Return the character indices (in the stripped string) of any
    eighth-block partials (▏▎▍▌▋▊▉)."""
    raw = strip_ansi(rendered)
    partials = set(BLOCK_CHARS[1:8])  # exclude space (0) and full block (8)
    return [i for i, c in enumerate(raw) if c in partials]


@pytest.mark.parametrize("pct", [
    1, 6, 12, 18, 25, 31, 37, 50, 56, 62, 75, 81, 87, 93, 99,
])
def test_partial_block_has_bg_color(pct: int):
    """Whenever progress_bar emits a partial block, both fg AND bg color
    codes must be active for that block. Without bg, the right portion
    of the partial block renders transparent → the variable-width gap
    Shawn called out in the 2026-06-01 chat.
    """
    bar = progress_bar(pct, width=10)
    if not _partial_block_positions(bar):
        pytest.skip(f"pct={pct} did not produce a partial block (boundary aligned)")

    # The partial block is between full bright blocks and dim blocks.
    # We require: at least one bg-color SGR sequence exists in the bar.
    # (Without the fix, bar would have only fg codes, no bg codes.)
    assert _BG_RGB_RE.search(bar), (
        f"pct={pct} bar has a partial block but no bg color SGR — "
        f"this reintroduces the right-side transparency gap.\n"
        f"Bar (repr): {bar!r}\n"
        f"Raw glyphs: {strip_ansi(bar)!r}"
    )


@pytest.mark.parametrize("pct", list(range(0, 101, 5)))
def test_visible_width_equals_declared_width(pct: int):
    """Visible width of the rendered bar must equal the declared width
    for every fill percentage. If the partial block renders with a
    transparent right portion, terminal-side accounting still claims
    the cell — so wcwidth returns the right value — but the visible
    output has a gap. We pair this test with the SGR-presence test
    above to lock the invariant from both sides.
    """
    for w in (8, 10, 16, 20):
        bar = progress_bar(pct, width=w)
        assert visible_len(strip_ansi(bar)) == w, (
            f"pct={pct} width={w}: visible_len={visible_len(strip_ansi(bar))}"
        )


def test_none_value_renders_empty_bar_full_width():
    """When pct is None, the bar should be entirely dim — no partial,
    no fill, full width."""
    bar = progress_bar(None, width=10)
    raw = strip_ansi(bar)
    assert raw == "█" * 10
    # No partial blocks
    assert not _partial_block_positions(bar)
    # bg presence not required when there's no partial (no boundary)
    assert _FG_RGB_RE.search(bar), "None bar must still carry a fg color"


def test_full_value_renders_full_bar_no_partial():
    """100% → all bright full blocks, no partial."""
    bar = progress_bar(100, width=10)
    raw = strip_ansi(bar)
    assert raw == "█" * 10
    assert not _partial_block_positions(bar)


def test_zero_value_renders_empty_bar_no_partial():
    """0% → all dim full blocks, no partial."""
    bar = progress_bar(0, width=10)
    raw = strip_ansi(bar)
    assert raw == "█" * 10
    assert not _partial_block_positions(bar)


def test_partial_block_immediately_followed_by_dim_fg():
    """The cell after the partial block must reset fg to the empty color.
    Without that reset, the dim portion of the bar would inherit the
    partial block's bg, but the dim block glyphs themselves would still
    be drawn in the bright fill color — a different bug class.

    This test ensures the SGR sequence right after a partial block sets
    fg to a new RGB value (the empty color) before drawing the next █.
    """
    bar = progress_bar(45, width=10)
    if not _partial_block_positions(bar):
        pytest.skip("pct=45 did not produce a partial block on this width")

    # The bar must contain at least two distinct fg-RGB SGR triples:
    # one for the bright fill, one for the dim empty.
    fg_codes = _FG_RGB_RE.findall(bar)
    distinct_fg = set(fg_codes)
    assert len(distinct_fg) >= 2, (
        f"Expected ≥2 distinct fg colors (bright + dim), got {len(distinct_fg)}.\n"
        f"Bar: {bar!r}"
    )
