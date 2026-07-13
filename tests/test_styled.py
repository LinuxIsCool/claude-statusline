"""Tests for the Styled primitive — visible-width-as-data.

`Styled` is the Stage-1 deliverable of the visible-width-as-data refactor.
It carries `visible_width` as a field next to a (possibly ANSI-styled) text
fragment, eliminating the need to recompute `visible_len` on every layout
pass.

These tests cover the type's construction, composition (__add__ / __radd__
with str + Styled), padding, truncation, and the f-string / len() shims
that let it flow transparently through legacy `str`-typed call sites.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from primitives import Styled, visible_len  # noqa: E402


# ── Construction ──────────────────────────────────────────────────────


def test_styled_holds_text_and_width():
    s = Styled("hi", 2)
    assert s.text == "hi"
    assert s.visible_width == 2


def test_styled_is_frozen():
    s = Styled("x", 1)
    with pytest.raises(Exception):  # FrozenInstanceError is dataclass-internal
        s.text = "y"  # type: ignore[misc]


def test_styled_rejects_negative_width():
    with pytest.raises(ValueError, match="visible_width must be >= 0"):
        Styled("x", -1)


def test_styled_zero_width_is_valid():
    s = Styled("", 0)
    assert s.text == ""
    assert s.visible_width == 0


def test_styled_empty_is_zero_width():
    s = Styled.empty()
    assert s.text == ""
    assert s.visible_width == 0


def test_from_text_computes_width():
    s = Styled.from_text("abc")
    assert s.text == "abc"
    assert s.visible_width == 3


def test_from_text_handles_ansi():
    """ANSI escapes don't add to visible_width."""
    raw = "\x1b[31mred\x1b[0m"
    s = Styled.from_text(raw)
    assert s.text == raw
    assert s.visible_width == 3


def test_from_text_handles_known_wide_emoji():
    """Lotus 🪷 is in the override table → 2 cells."""
    s = Styled.from_text("🪷")
    assert s.visible_width == 2


# ── Composition: Styled + Styled ──────────────────────────────────────


def test_add_styled_concatenates_text_and_sums_width():
    a = Styled("ab", 2)
    b = Styled("cd", 2)
    out = a + b
    assert out.text == "abcd"
    assert out.visible_width == 4


def test_add_preserves_known_widths_even_when_text_has_ansi():
    """When both halves carry pre-computed widths, no recomputation happens."""
    a = Styled("\x1b[31mhi\x1b[0m", 2)  # explicitly 2 cells
    b = Styled("\x1b[32mbye\x1b[0m", 3)
    out = a + b
    # Width is summed from fields; the result does NOT redo visible_len.
    assert out.visible_width == 5


# ── Composition: Styled + str ─────────────────────────────────────────


def test_add_str_on_right_computes_width():
    a = Styled("x", 1)
    out = a + " "
    assert out.text == "x "
    assert out.visible_width == 2


def test_add_str_on_left_via_radd():
    """`" " + Styled(...)` invokes Styled.__radd__."""
    a = Styled("x", 1)
    out = " " + a
    assert out.text == " x"
    assert out.visible_width == 2


def test_add_chain_of_str_and_styled():
    a = Styled("a", 1)
    b = Styled("b", 1)
    out = a + " " + b
    assert out.text == "a b"
    assert out.visible_width == 3


# ── String coercion shims ─────────────────────────────────────────────


def test_str_returns_text():
    s = Styled("\x1b[31mhi\x1b[0m", 2)
    assert str(s) == "\x1b[31mhi\x1b[0m"


def test_fstring_uses_text():
    """f-strings call str() on each piece — should yield the styled bytes."""
    s = Styled("hello", 5)
    assert f"<{s}>" == "<hello>"


def test_len_returns_visible_width():
    """`len(styled)` returns visible cells, not byte length of styled text."""
    s = Styled("\x1b[31mhi\x1b[0m", 2)
    # Byte length of `text` would be 10; visible cells == 2.
    assert len(s) == 2


# ── Padding ───────────────────────────────────────────────────────────


def test_padded_left_align_appends_spaces():
    s = Styled("hi", 2).padded(5, "left")
    assert s.text == "hi   "
    assert s.visible_width == 5


def test_padded_right_align_prepends_spaces():
    s = Styled("hi", 2).padded(5, "right")
    assert s.text == "   hi"
    assert s.visible_width == 5


def test_padded_center_splits_extra_to_left():
    """6 - 2 = 4 → 2 left, 2 right."""
    s = Styled("hi", 2).padded(6, "center")
    assert s.text == "  hi  "
    assert s.visible_width == 6


def test_padded_center_with_odd_extra_floors_left():
    """5 - 2 = 3 → 1 left (3 // 2), 2 right (3 - 1)."""
    s = Styled("hi", 2).padded(5, "center")
    assert s.text == " hi  "
    assert s.visible_width == 5


def test_padded_noop_when_already_wide_enough():
    s = Styled("hello", 5)
    assert s.padded(3) is s
    assert s.padded(5) is s


def test_padded_unknown_align_defaults_to_left():
    s = Styled("hi", 2).padded(4, "garbage")
    assert s.text == "hi  "


# ── Truncation ────────────────────────────────────────────────────────


def test_truncated_noop_when_under_limit():
    s = Styled("hi", 2)
    assert s.truncated(5) is s


def test_truncated_clips_and_appends_ellipsis():
    s = Styled("hello world", 11).truncated(8)
    # 8 - 1 (ellipsis) = 7 visible chars from "hello world"
    assert s.text == "hello w…"
    assert s.visible_width == 8


def test_truncated_strips_ansi_lossy():
    """ANSI codes are stripped during truncation (documented lossy behavior)."""
    raw = "\x1b[31mhello world\x1b[0m"
    s = Styled(raw, 11).truncated(8)
    # ANSI is gone after truncation.
    assert "\x1b" not in s.text
    assert s.visible_width == 8


def test_truncated_max_width_zero_returns_empty():
    s = Styled("hello", 5).truncated(0)
    assert s.text == ""
    assert s.visible_width == 0


def test_truncated_no_room_for_ellipsis_emits_bare_prefix():
    """When max_width is smaller than the ellipsis width, drop the ellipsis."""
    s = Styled("hello", 5).truncated(1)
    # ellipsis is 1 cell wide; max_width == 1 → max_width <= ell_width → bare prefix
    assert s.text == "h"
    assert s.visible_width == 1


def test_truncated_with_custom_ellipsis():
    s = Styled("hello world", 11).truncated(8, ellipsis="...")
    # 8 - 3 = 5 visible chars from "hello world"
    assert s.text == "hello..."
    assert s.visible_width == 8


def test_truncated_respects_wide_char_boundary():
    """Truncation must not split a 2-cell emoji in half."""
    # Lotus 🪷 (2 cells) + "abc" (3 cells) = 5 cells total
    s = Styled.from_text("🪷abc")
    assert s.visible_width == 5
    # Truncate to 3 → ellipsis (1) + content (2). Content "🪷" is exactly 2
    # cells, so it survives; the 3 'abc' chars are cut.
    out = s.truncated(3)
    assert out.visible_width == 3
    # The lotus should NOT be split (would be invalid UTF if it could be).
    assert "🪷" in out.text


# ── Pythonic identity: __add__ + Styled.empty() ───────────────────────


def test_empty_is_left_identity_for_add():
    a = Styled("x", 1)
    out = Styled.empty() + a
    assert out.text == a.text
    assert out.visible_width == a.visible_width


def test_empty_is_right_identity_for_add():
    a = Styled("x", 1)
    out = a + Styled.empty()
    assert out.text == a.text
    assert out.visible_width == a.visible_width
