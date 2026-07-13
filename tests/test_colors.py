"""Tests for lib/colors.py — terminal-caps-aware ANSI emission."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import terminal_caps  # noqa: E402


def _clear_color_env(mp):
    """Scrub anything that could leak in from the dev shell."""
    for var in ("NO_COLOR", "COLORTERM", "TERM", "TERM_PROGRAM",
                "LC_ALL", "LC_CTYPE", "LANG"):
        mp.delenv(var, raising=False)


def _reload_colors():
    """Reset terminal_caps cache and reload colors so module-level
    constants (RST/BOLD/DIM/ITALIC) are recomputed from the current env.
    Returns the freshly-loaded colors module.
    """
    terminal_caps._reset_cache_for_tests()
    import colors  # noqa: WPS433 — late import is intentional
    return importlib.reload(colors)


@pytest.fixture(autouse=True)
def _reset_caps_cache():
    """Clear the detect() cache before AND after each test."""
    terminal_caps._reset_cache_for_tests()
    yield
    terminal_caps._reset_cache_for_tests()


# ── NO_COLOR ──────────────────────────────────────────────────────────

def test_no_color_returns_empty_for_fg(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")
    colors = _reload_colors()
    assert colors.fg("#ff0000") == ""


def test_no_color_returns_empty_for_bg(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")
    colors = _reload_colors()
    assert colors.bg("#00ff00") == ""


def test_no_color_collapses_style_constants(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")
    colors = _reload_colors()
    assert colors.RST == ""
    assert colors.BOLD == ""
    assert colors.DIM == ""
    assert colors.ITALIC == ""


def test_no_color_wins_over_colorterm(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("COLORTERM", "truecolor")
    colors = _reload_colors()
    assert colors.fg("#ff0000") == ""
    assert colors.bg("#00ff00") == ""


def test_styled_emits_only_text_when_no_color(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")
    colors = _reload_colors()
    out = colors.styled("hello", "#ff0000", bold=True, dim=True)
    assert out == "hello"
    assert "\x1b" not in out


# ── color_depth == 0 (unknown TERM) ───────────────────────────────────

def test_unknown_term_returns_empty(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("TERM", "dumb")
    colors = _reload_colors()
    assert colors.fg("#ff0000") == ""
    assert colors.bg("#00ff00") == ""


# ── color_depth == 24 (truecolor) ─────────────────────────────────────

def test_truecolor_emits_rgb_fg(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("COLORTERM", "truecolor")
    colors = _reload_colors()
    assert colors.fg("#ff0000") == "\x1b[38;2;255;0;0m"


def test_truecolor_emits_rgb_bg(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("COLORTERM", "truecolor")
    colors = _reload_colors()
    assert colors.bg("#00ff00") == "\x1b[48;2;0;255;0m"


def test_truecolor_keeps_reset_intact(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("COLORTERM", "truecolor")
    colors = _reload_colors()
    assert colors.RST == "\x1b[0m"
    assert colors.BOLD == "\x1b[1m"
    assert colors.DIM == "\x1b[2m"


# ── color_depth == 8 (xterm-256color) ─────────────────────────────────

def test_256_color_emits_indexed_fg(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("TERM", "xterm-256color")
    colors = _reload_colors()
    out = colors.fg("#ff0000")
    assert out.startswith("\x1b[38;5;")
    assert out.endswith("m")


def test_256_color_emits_indexed_bg(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("TERM", "xterm-256color")
    colors = _reload_colors()
    out = colors.bg("#00ff00")
    assert out.startswith("\x1b[48;5;")
    assert out.endswith("m")


def test_256_color_pure_red_maps_to_cube_corner(monkeypatch):
    """In the 6x6x6 cube, #ff0000 -> 16 + 36*5 + 6*0 + 0 == 196."""
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("TERM", "xterm-256color")
    colors = _reload_colors()
    assert colors.fg("#ff0000") == "\x1b[38;5;196m"


def test_256_color_grayscale_uses_ramp(monkeypatch):
    """Mid-grey (#808080) should land on the 24-step grayscale ramp."""
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("TERM", "xterm-256color")
    colors = _reload_colors()
    out = colors.fg("#808080")
    # Ramp lives between indices 232-255.
    idx = int(out.removeprefix("\x1b[38;5;").removesuffix("m"))
    assert 232 <= idx <= 255


# ── color_depth == 4 (16-color) ───────────────────────────────────────

def test_16_color_emits_basic_sgr_for_red(monkeypatch):
    """#ff0000 should fall on bright red (SGR 91) under the 16-color match."""
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("TERM", "xterm")
    colors = _reload_colors()
    out = colors.fg("#ff0000")
    # Either standard red (\x1b[31m) or bright red (\x1b[91m) is acceptable.
    # Our nearest-match table puts #ff0000 on bright red (index 9).
    assert out == "\x1b[91m"


def test_16_color_emits_bg_for_green(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("TERM", "xterm")
    colors = _reload_colors()
    out = colors.bg("#00ff00")
    # Bright green -> SGR 102 on background.
    assert out == "\x1b[102m"


def test_16_color_black_emits_standard(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("TERM", "xterm")
    colors = _reload_colors()
    assert colors.fg("#000000") == "\x1b[30m"


# ── Bad input still degrades safely ───────────────────────────────────

def test_bad_hex_input_does_not_crash(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("COLORTERM", "truecolor")
    colors = _reload_colors()
    # _hex_to_rgb returns (255, 255, 255) on bad input.
    assert colors.fg("not-a-hex") == "\x1b[38;2;255;255;255m"


# ── styled() composition ──────────────────────────────────────────────

def test_styled_composes_truecolor(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("COLORTERM", "truecolor")
    colors = _reload_colors()
    out = colors.styled("hi", "#ff0000", bold=True)
    assert out == "\x1b[38;2;255;0;0m\x1b[1mhi\x1b[0m"


# ── styled_w() — opt-in Styled-returning constructor ──────────────────


def test_styled_w_returns_styled_instance(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("COLORTERM", "truecolor")
    colors = _reload_colors()
    from primitives import Styled
    out = colors.styled_w("hi", "#ff0000")
    assert isinstance(out, Styled)


def test_styled_w_visible_width_excludes_ansi(monkeypatch):
    """The width field must reflect only the user-visible cells."""
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("COLORTERM", "truecolor")
    colors = _reload_colors()
    out = colors.styled_w("hello", "#ff0000", bold=True, dim=True)
    # Visible cells = 5, regardless of how many ANSI bytes wrap them.
    assert out.visible_width == 5
    # ANSI escapes are present in the raw text.
    assert "\x1b" in out.text
    # Raw bytes follow the same pattern as legacy styled().
    assert out.text.endswith("\x1b[0m")
    assert "hello" in out.text


def test_styled_w_no_color_emits_bare_text(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")
    colors = _reload_colors()
    out = colors.styled_w("hello", "#ff0000", bold=True, dim=True)
    # No ANSI when NO_COLOR is set; visible_width still correct.
    assert out.text == "hello"
    assert out.visible_width == 5
    assert "\x1b" not in out.text


def test_styled_w_matches_styled_legacy_text(monkeypatch):
    """styled_w(...).text MUST equal styled(...) bytes for byte-for-byte parity."""
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("COLORTERM", "truecolor")
    colors = _reload_colors()
    legacy = colors.styled("payload", "#00ff00", bold=True)
    new = colors.styled_w("payload", "#00ff00", bold=True)
    assert new.text == legacy


def test_styled_w_composes_with_str_in_either_order(monkeypatch):
    """Real-world usage: styled_w(...) + " " + styled_w(...)."""
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")
    colors = _reload_colors()
    a = colors.styled_w("a", "#ff0000")
    b = colors.styled_w("b", "#00ff00")
    out = a + " " + b
    assert out.text == "a b"
    assert out.visible_width == 3
