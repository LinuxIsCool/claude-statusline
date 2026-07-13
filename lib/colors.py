"""Color palettes and ANSI color helpers for claude-statusline.

Honors terminal capabilities (NO_COLOR + color depth) via terminal_caps.detect():
- no_color or color_depth==0  -> emits "" (no ANSI at all)
- color_depth==4              -> 16-color SGR (\\x1b[3<n>m / \\x1b[4<n>m)
- color_depth==8              -> 256-color SGR (\\x1b[38;5;<n>m / \\x1b[48;5;<n>m)
- color_depth==24             -> truecolor SGR (\\x1b[38;2;r;g;bm / \\x1b[48;2;r;g;bm)

SGR style constants (RST/BOLD/DIM/ITALIC) collapse to "" when no_color is set
so renderers can keep concatenating without width drift. Constants are
resolved at import time because terminal capabilities are stable for the
process lifetime (NO_COLOR is set in shell env at launch).
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

# Optionally make a claude-personas checkout importable for canonical
# PERSONA_COLORS. Resolution order: $CLAUDE_PERSONAS_SRC, then the sibling
# plugin in a monorepo/marketplace layout. Absence is fine: colors fall
# back to the vendored table below.
_personas_src = os.environ.get("CLAUDE_PERSONAS_SRC", "")
if not _personas_src:
    _sibling = Path(__file__).resolve().parents[2] / "claude-personas" / "src"
    if _sibling.is_dir():
        _personas_src = str(_sibling)
if _personas_src and _personas_src not in sys.path:
    sys.path.insert(0, _personas_src)

from terminal_caps import detect as _detect_caps  # noqa: E402

# Raw ANSI escape constants — used when color is enabled.
_RST_RAW = "\033[0m"
_BOLD_RAW = "\033[1m"
_DIM_RAW = "\033[2m"
_ITALIC_RAW = "\033[3m"


def _style_or_empty(escape: str) -> str:
    """Return the SGR escape unless NO_COLOR is in effect."""
    return "" if _detect_caps().no_color else escape


# Module-level style constants. Computed once at import time from detected
# terminal capabilities (matches the cache lifetime of terminal_caps.detect()).
# Tests that flip NO_COLOR mid-process should call
# `terminal_caps._reset_cache_for_tests()` AND `importlib.reload(colors)`.
RST = _style_or_empty(_RST_RAW)
BOLD = _style_or_empty(_BOLD_RAW)
DIM = _style_or_empty(_DIM_RAW)
ITALIC = _style_or_empty(_ITALIC_RAW)


_HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


@dataclass(frozen=True)
class ColorPalette:
    """Semantic color palette for statusline rendering."""

    bg: str
    fg: str
    fg_dim: str
    ok: str
    warn: str
    error: str
    info: str
    accent: str
    separator: str

    def __post_init__(self):
        for field_name in ('bg', 'fg', 'fg_dim', 'ok', 'warn', 'error',
                           'info', 'accent', 'separator'):
            val = getattr(self, field_name)
            if not _HEX_RE.match(val):
                raise ValueError(
                    f"ColorPalette.{field_name} must be #RRGGBB, got {val!r}"
                )


CATPPUCCIN_MOCHA = ColorPalette(
    bg="#1e1e2e",
    fg="#cdd6f4",
    fg_dim="#6c7086",
    ok="#a6e3a1",
    warn="#f9e2af",
    error="#f38ba8",
    info="#89b4fa",
    accent="#cba6f7",
    separator="#45475a",
)

NORD_FROST = ColorPalette(
    bg="#2e3440",
    fg="#eceff4",
    fg_dim="#4c566a",
    ok="#a3be8c",
    warn="#ebcb8b",
    error="#bf616a",
    info="#88c0d0",
    accent="#b48ead",
    separator="#3b4252",
)

CATPPUCCIN_MACCHIATO = ColorPalette(
    bg="#24273a",
    fg="#cad3f5",
    fg_dim="#6e738d",
    ok="#a6da95",
    warn="#eed49f",
    error="#ed8796",
    info="#8aadf4",
    accent="#c6a0f6",
    separator="#363a4f",
)

CATPPUCCIN_FRAPPE = ColorPalette(
    bg="#303446",
    fg="#c6d0f5",
    fg_dim="#737994",
    ok="#a6d189",
    warn="#e5c890",
    error="#e78284",
    info="#8caaee",
    accent="#ca9ee6",
    separator="#414559",
)

CATPPUCCIN_LATTE = ColorPalette(
    bg="#eff1f5",
    fg="#4c4f69",
    fg_dim="#9ca0b0",
    ok="#40a02b",
    warn="#df8e1d",
    error="#d20f39",
    info="#1e66f5",
    accent="#8839ef",
    separator="#ccd0da",
)

NORD_AURORA = ColorPalette(
    bg="#2e3440",
    fg="#eceff4",
    fg_dim="#4c566a",
    ok="#a3be8c",
    warn="#ebcb8b",
    error="#bf616a",
    info="#81a1c1",
    accent="#b48ead",
    separator="#3b4252",
)

NORD_POLAR = ColorPalette(
    bg="#2e3440",
    fg="#d8dee9",
    fg_dim="#4c566a",
    ok="#a3be8c",
    warn="#ebcb8b",
    error="#bf616a",
    info="#5e81ac",
    accent="#b48ead",
    separator="#3b4252",
)

SOLARIZED_DARK = ColorPalette(
    bg="#002b36",
    fg="#839496",
    fg_dim="#586e75",
    ok="#859900",
    warn="#b58900",
    error="#dc322f",
    info="#268bd2",
    accent="#6c71c4",
    separator="#073642",
)

SOLARIZED_LIGHT = ColorPalette(
    bg="#fdf6e3",
    fg="#657b83",
    fg_dim="#93a1a1",
    ok="#859900",
    warn="#b58900",
    error="#dc322f",
    info="#268bd2",
    accent="#6c71c4",
    separator="#eee8d5",
)

_PALETTES: Dict[str, ColorPalette] = {
    "catppuccin_mocha": CATPPUCCIN_MOCHA,
    "catppuccin_macchiato": CATPPUCCIN_MACCHIATO,
    "catppuccin_frappe": CATPPUCCIN_FRAPPE,
    "catppuccin_latte": CATPPUCCIN_LATTE,
    "nord_frost": NORD_FROST,
    "nord_aurora": NORD_AURORA,
    "nord_polar": NORD_POLAR,
    "solarized_dark": SOLARIZED_DARK,
    "solarized_light": SOLARIZED_LIGHT,
}


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Parse '#RRGGBB' to (r, g, b) tuple. Returns white on bad input."""
    try:
        h = hex_color.lstrip("#")
        if len(h) != 6:
            return (255, 255, 255)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except (ValueError, IndexError):
        return (255, 255, 255)


# ── Color-depth downconversion ────────────────────────────────────────

def _rgb_to_256(rgb: tuple[int, int, int]) -> int:
    """Map an RGB triple to the xterm-256 palette.

    Uses the 6x6x6 color cube (indices 16-231) for chromatic colors and
    the 24-step grayscale ramp (232-255) when R==G==B. Matches the
    common conversion used by tmux/iTerm/Alacritty 256-mode fallback.
    """
    r, g, b = rgb
    # Grayscale ramp: 24 steps from #080808 to #eeeeee.
    if r == g == b:
        if r < 8:
            return 16  # black in the cube
        if r > 248:
            return 231  # white in the cube
        return 232 + (r - 8) // 10
    # 6x6x6 cube. Each axis maps to {0,1,2,3,4,5} via the standard
    # xterm step table [0, 95, 135, 175, 215, 255].
    def _axis(v: int) -> int:
        if v < 48:
            return 0
        if v < 115:
            return 1
        return (v - 35) // 40
    return 16 + 36 * _axis(r) + 6 * _axis(g) + _axis(b)


# Standard 16-ANSI palette in approximate sRGB. Indices 0-7 are the
# normal colors; 8-15 are the bright variants. Values follow the xterm
# defaults (close enough to most terminal themes for nearest-match).
_ANSI16_RGB: tuple[tuple[int, int, int], ...] = (
    (0, 0, 0),         # 0  black
    (205, 0, 0),       # 1  red
    (0, 205, 0),       # 2  green
    (205, 205, 0),     # 3  yellow
    (0, 0, 238),       # 4  blue
    (205, 0, 205),     # 5  magenta
    (0, 205, 205),     # 6  cyan
    (229, 229, 229),   # 7  white
    (127, 127, 127),   # 8  bright black (grey)
    (255, 0, 0),       # 9  bright red
    (0, 255, 0),       # 10 bright green
    (255, 255, 0),     # 11 bright yellow
    (92, 92, 255),     # 12 bright blue
    (255, 0, 255),     # 13 bright magenta
    (0, 255, 255),     # 14 bright cyan
    (255, 255, 255),   # 15 bright white
)


def _rgb_to_16(rgb: tuple[int, int, int]) -> int:
    """Nearest of the 16 standard ANSI colors (squared-distance match).

    Returns the palette index 0..15. Callers map 0-7 to `3<n>`/`4<n>` and
    8-15 to the bright SGR variants `9<n-8>`/`10<n-8>`.
    """
    r, g, b = rgb
    best_idx = 0
    best_dist = 1 << 30
    for idx, (pr, pg, pb) in enumerate(_ANSI16_RGB):
        d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if d < best_dist:
            best_dist = d
            best_idx = idx
    return best_idx


def _ansi16_sgr(idx: int, *, is_bg: bool) -> str:
    """Build the SGR code for a 16-color palette index (0..15)."""
    if idx < 8:
        return f"\033[{4 if is_bg else 3}{idx}m"
    # Bright variants: SGR 90-97 (fg) and 100-107 (bg).
    base = 100 if is_bg else 90
    return f"\033[{base + (idx - 8)}m"


def _color_escape(hex_color: str, *, is_bg: bool) -> str:
    """Emit an ANSI color SGR appropriate for the detected color depth."""
    caps = _detect_caps()
    if caps.no_color or caps.color_depth == 0:
        return ""
    rgb = _hex_to_rgb(hex_color)
    if caps.color_depth >= 24:
        r, g, b = rgb
        return f"\033[{48 if is_bg else 38};2;{r};{g};{b}m"
    if caps.color_depth >= 8:
        return f"\033[{48 if is_bg else 38};5;{_rgb_to_256(rgb)}m"
    # 4-bit (16-color) fallback.
    return _ansi16_sgr(_rgb_to_16(rgb), is_bg=is_bg)


def fg(hex_color: str) -> str:
    """ANSI foreground escape from '#RRGGBB', tiered by terminal color depth."""
    return _color_escape(hex_color, is_bg=False)


def bg(hex_color: str) -> str:
    """ANSI background escape from '#RRGGBB', tiered by terminal color depth."""
    return _color_escape(hex_color, is_bg=True)


def styled(text: str, color: str, bold: bool = False, dim: bool = False) -> str:
    """Apply truecolor foreground + optional bold/dim, with auto-reset.

    Returns a raw `str` for backward compatibility with the 100+ existing
    theme call sites. Prefer `styled_w()` in new code — it returns a
    `Styled` object that carries visible_width as data, eliminating
    downstream visible_len recomputations.
    """
    parts = [fg(color)]
    if bold:
        parts.append(BOLD)
    if dim:
        parts.append(DIM)
    parts.append(text)
    parts.append(RST)
    return "".join(parts)


def styled_w(text: str, color: str, bold: bool = False, dim: bool = False):
    """Opt-in constructor: same as `styled()` but returns `Styled`.

    The returned `Styled` carries `visible_width = visible_len(text)` —
    computed ONCE here. ANSI escapes added by this function are zero-width
    and never confuse downstream layout code that consumes the field.

    Migration target for the visible-width-as-data refactor. New code (and
    incrementally-migrated row builders) should reach for `styled_w()`;
    legacy code keeps using `styled()` until ported.
    """
    # Import lazily to avoid a circular import: primitives imports from
    # colors (RST, fg), and Styled is defined in primitives.
    from primitives import Styled, visible_len  # noqa: WPS433
    prefix_parts = [fg(color)]
    if bold:
        prefix_parts.append(BOLD)
    if dim:
        prefix_parts.append(DIM)
    prefix = "".join(prefix_parts)
    suffix = RST if prefix else ""
    return Styled(prefix + text + suffix, visible_len(text))


def get_palette(name: str) -> ColorPalette:
    """Get a palette by name. Defaults to CATPPUCCIN_MOCHA if not found."""
    return _PALETTES.get(name, CATPPUCCIN_MOCHA)


# ── Persona colors ────────────────────────────────────────────────────

# Named persona colors → hex. When a claude-personas checkout is importable
# (see sys.path setup at the top of this module) its table is canonical;
# otherwise this vendored copy of the same Catppuccin Mocha named-color
# table applies. Role YAML uses named colors: capabilities.color: cyan/etc.

_FALLBACK_PERSONA_COLORS: Dict[str, str] = {
    "cyan": "#89dceb",
    "green": "#a6e3a1",
    "yellow": "#f9e2af",
    "blue": "#89b4fa",
    "magenta": "#cba6f7",
    "red": "#f38ba8",
    "orange": "#fab387",
    "pink": "#f5c2e7",
    "white": "#cdd6f4",
}

try:
    from claude_personas.colors import PERSONA_COLORS  # noqa: E402
except ImportError:
    PERSONA_COLORS = _FALLBACK_PERSONA_COLORS


def resolve_persona_color(name: str) -> str:
    """Resolve a named persona color to hex. Returns empty string if unknown."""
    return PERSONA_COLORS.get(name.lower(), "") if name else ""
