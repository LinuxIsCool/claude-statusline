"""Tests for lib/terminal_caps.py — terminal capability detection."""

from __future__ import annotations

import pytest

import terminal_caps
from terminal_caps import TerminalCaps, detect, is_narrow


@pytest.fixture(autouse=True)
def _reset_cache():
    """Clear the detect() cache before AND after each test."""
    terminal_caps._reset_cache_for_tests()
    yield
    terminal_caps._reset_cache_for_tests()


def _clear_color_env(mp):
    """Helper: scrub anything that could leak in from the dev shell."""
    for var in ("NO_COLOR", "COLORTERM", "TERM", "TERM_PROGRAM",
                "LC_ALL", "LC_CTYPE", "LANG"):
        mp.delenv(var, raising=False)


def test_detect_returns_terminal_caps_instance(monkeypatch):
    _clear_color_env(monkeypatch)
    caps = detect()
    assert isinstance(caps, TerminalCaps)
    assert isinstance(caps.is_tty, bool)
    assert isinstance(caps.color_depth, int)
    assert isinstance(caps.width, int)
    assert isinstance(caps.height, int)


def test_no_color_forces_color_depth_zero(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")
    # Even with COLORTERM=truecolor, NO_COLOR wins.
    monkeypatch.setenv("COLORTERM", "truecolor")
    caps = detect()
    assert caps.no_color is True
    assert caps.color_depth == 0


def test_colorterm_truecolor_yields_24(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("COLORTERM", "truecolor")
    caps = detect()
    assert caps.color_depth == 24


def test_colorterm_24bit_yields_24(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("COLORTERM", "24bit")
    caps = detect()
    assert caps.color_depth == 24


def test_term_256color_yields_8(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("TERM", "xterm-256color")
    caps = detect()
    assert caps.color_depth == 8


def test_term_xterm_yields_4(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("TERM", "xterm")
    caps = detect()
    assert caps.color_depth == 4


def test_unknown_term_yields_0(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("TERM", "dumb")
    caps = detect()
    assert caps.color_depth == 0


def test_is_narrow_true_for_tiny_terminal(monkeypatch):
    _clear_color_env(monkeypatch)
    import os as _os
    monkeypatch.setattr(
        "shutil.get_terminal_size",
        lambda fallback=(80, 24): _os.terminal_size((40, 24)),
    )
    assert is_narrow(threshold=100) is True


def test_is_narrow_false_for_wide_terminal(monkeypatch):
    _clear_color_env(monkeypatch)
    import os as _os
    monkeypatch.setattr(
        "shutil.get_terminal_size",
        lambda fallback=(80, 24): _os.terminal_size((200, 50)),
    )
    assert is_narrow(threshold=100) is False


def test_supports_osc8_for_alacritty(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("TERM_PROGRAM", "Alacritty")
    caps = detect()
    assert caps.term_program == "Alacritty"
    assert caps.supports_osc8 is True


def test_supports_osc8_for_iterm(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    caps = detect()
    assert caps.supports_osc8 is True


def test_supports_osc8_false_for_unknown_terminal(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("TERM_PROGRAM", "SomeRandomTerm")
    caps = detect()
    assert caps.supports_osc8 is False


def test_supports_synchronized_for_alacritty(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("TERM_PROGRAM", "Alacritty")
    caps = detect()
    assert caps.supports_synchronized is True


def test_supports_synchronized_false_for_iterm(monkeypatch):
    """iTerm.app supports OSC 8 but not Mode 2026 synchronized output."""
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    caps = detect()
    assert caps.supports_osc8 is True
    assert caps.supports_synchronized is False


def test_supports_unicode_for_utf8_lang(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    caps = detect()
    assert caps.supports_unicode is True


def test_supports_unicode_false_for_c_locale(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("LANG", "C")
    monkeypatch.setenv("LC_ALL", "C")
    caps = detect()
    assert caps.supports_unicode is False


def test_cache_persists_across_calls(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("COLORTERM", "truecolor")
    first = detect()
    # Mutate the env — second call should still see the cached value.
    monkeypatch.setenv("COLORTERM", "")
    monkeypatch.setenv("NO_COLOR", "1")
    second = detect()
    assert first is second
    assert second.color_depth == 24  # still truecolor from first call


def test_cache_reset_helper_works(monkeypatch):
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("COLORTERM", "truecolor")
    first = detect()
    terminal_caps._reset_cache_for_tests()
    monkeypatch.delenv("COLORTERM", raising=False)
    second = detect()
    assert first is not second
    assert second.color_depth == 0


def test_terminal_caps_is_frozen():
    caps = detect()
    with pytest.raises(Exception):  # FrozenInstanceError
        caps.width = 999  # type: ignore[misc]
