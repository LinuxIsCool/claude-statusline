"""Terminal capability detection — cached once for the lifetime of the process.

Used to gate rendering decisions in the statusline:
- truecolor vs 256 vs 16-color vs mono fallback
- NO_COLOR honored (per https://no-color.org)
- narrow-terminal fallback (single-line layouts)
- OSC 8 hyperlinks (clickable session IDs in supporting terminals)
- DEC mode 2026 synchronized output (flicker-free repaints)

Cached on first call so the cost is paid exactly once per process.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass

# Terminals known to support OSC 8 hyperlinks.
_OSC8_TERMINALS: frozenset[str] = frozenset(
    {"Alacritty", "iTerm.app", "WezTerm", "kitty"}
)

# Terminals known to support DEC mode 2026 synchronized output.
_SYNCHRONIZED_TERMINALS: frozenset[str] = frozenset(
    {"Alacritty", "kitty", "WezTerm"}
)


@dataclass(frozen=True)
class TerminalCaps:
    """Detected once at first call, cached for lifetime of process."""

    is_tty: bool
    no_color: bool
    color_depth: int  # 0 (mono), 4 (16), 8 (256), 24 (truecolor)
    width: int
    height: int
    supports_unicode: bool
    term_program: str
    supports_osc8: bool
    supports_synchronized: bool


# Module-level cache. Populated on first detect() call.
_cached_caps: TerminalCaps | None = None


def _detect_color_depth(no_color: bool) -> int:
    """Return color depth: 0 (mono), 4, 8, or 24."""
    if no_color:
        return 0
    colorterm = os.environ.get("COLORTERM", "").lower()
    if colorterm in ("truecolor", "24bit"):
        return 24
    term = os.environ.get("TERM", "").lower()
    if "256color" in term:
        return 8
    if "color" in term or "xterm" in term:
        return 4
    return 0


def _detect_unicode() -> bool:
    """True if the locale advertises UTF-8."""
    for var in ("LC_ALL", "LC_CTYPE", "LANG"):
        v = os.environ.get(var, "")
        if "UTF-8" in v.upper() or "UTF8" in v.upper():
            return True
    return False


def detect() -> TerminalCaps:
    """Detect terminal capabilities. Cached after first call."""
    global _cached_caps
    if _cached_caps is not None:
        return _cached_caps

    is_tty = bool(getattr(sys.stdout, "isatty", lambda: False)())
    no_color = bool(os.environ.get("NO_COLOR"))
    color_depth = _detect_color_depth(no_color)

    size = shutil.get_terminal_size(fallback=(80, 24))
    width, height = size.columns, size.lines

    supports_unicode = _detect_unicode()
    term_program = os.environ.get("TERM_PROGRAM", "")
    supports_osc8 = term_program in _OSC8_TERMINALS
    supports_synchronized = term_program in _SYNCHRONIZED_TERMINALS

    _cached_caps = TerminalCaps(
        is_tty=is_tty,
        no_color=no_color,
        color_depth=color_depth,
        width=width,
        height=height,
        supports_unicode=supports_unicode,
        term_program=term_program,
        supports_osc8=supports_osc8,
        supports_synchronized=supports_synchronized,
    )
    return _cached_caps


def is_narrow(threshold: int = 100) -> bool:
    """True if terminal is narrower than threshold cols."""
    return detect().width < threshold


def _reset_cache_for_tests() -> None:
    """Test-only: clear the module-level cache so detect() re-runs."""
    global _cached_caps
    _cached_caps = None
