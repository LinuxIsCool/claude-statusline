"""Visual building blocks for claude-statusline themes.

All functions are pure, no side effects, stdlib-only imports.
These are the atoms that themes compose into statusline output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from colors import RST, fg


# ── Progress bars ────────────────────────────────────────────────────

BLOCK_CHARS = " ▏▎▍▌▋▊▉█"
SPARKLINE_CHARS = "▁▂▃▄▅▆▇█"


def progress_bar(
    pct: float | None,
    width: int = 16,
    fill_color: str = "#89b4fa",
    empty_color: str = "#313244",
) -> str:
    """Sub-block-precise progress bar — single-glyph for full + dim, gap-
    free at the partial-block boundary.

    Full cells: bright █ (fill_color foreground).
    Boundary cell: an eighth-block partial (▏▎▍▌▋▊▉) with BOTH foreground
    (fill_color, left portion) AND background (empty_color, right portion)
    set explicitly. Without the bg, the right portion of the partial
    renders transparent and the apparent bar shows a variable-width gap
    proportional to (1 - partial_fraction). See task-552 §Phase 1 + the
    2026-06-01 design chat.
    Dim cells: dim █ (empty_color foreground).
    """
    # Lazy import to avoid pulling bg in by default for other callers.
    from colors import bg as _bg

    if pct is None:
        return fg(empty_color) + "█" * width + RST

    filled_exact = max(0.0, min(100.0, pct)) / 100.0 * width
    full_blocks = int(filled_exact)
    partial_idx = int((filled_exact - full_blocks) * 8)

    bar = fg(fill_color) + "█" * full_blocks
    if full_blocks < width and partial_idx > 0:
        # Partial-block: fg paints the LEFT portion of the cell;
        # bg fills the RIGHT portion (closes the gap).
        bar += _bg(empty_color) + BLOCK_CHARS[partial_idx]
        full_blocks += 1
    # Empty portion: same █ glyph, dim color foreground. Reset bg first
    # so it doesn't inherit empty_color as a background under the dim
    # blocks (which would render identically but emits redundant SGR).
    if full_blocks < width:
        bar += "\x1b[49m" + fg(empty_color) + "█" * (width - full_blocks)
    bar += RST
    return bar


def sparkline(values: list[float], color: str = "#89b4fa") -> str:
    """Sparkline from a list of values using ▁▂▃▄▅▆▇█ chars."""
    if not values:
        return ""
    lo = min(values)
    hi = max(values)
    rng = hi - lo if hi > lo else 1.0
    chars = []
    for v in values:
        idx = int((v - lo) / rng * 7)
        idx = max(0, min(7, idx))
        chars.append(SPARKLINE_CHARS[idx])
    return fg(color) + "".join(chars) + RST


# ── Separators ───────────────────────────────────────────────────────

def sep(color: str = "#45475a", style: str = "pipe") -> str:
    """Separator between statusline segments.

    Styles: pipe │, dot ·, dash ─, thin ╎, space, arrow
    """
    chars = {
        "pipe": "│",
        "dot": "·",
        "dash": "─",
        "thin": "╎",
        "space": " ",
        "arrow": "",
    }
    char = chars.get(style, "│")
    return f" {fg(color)}{char}{RST} "


def powerline_sep(left_bg: str, right_bg: str) -> str:
    """Powerline-style  separator between two background colors.

    If right_bg is empty, emits RST to return to terminal default background
    rather than rendering a white block (which _hex_to_rgb("") would produce).
    """
    from colors import bg as bg_fn
    if not right_bg:
        return f"{RST}{fg(left_bg)}{RST}"
    return f"{bg_fn(right_bg)}{fg(left_bg)}{RST}"


# ── Formatting helpers ───────────────────────────────────────────────

def fmt_pct(pct: float | None) -> str:
    """Format percentage: 42%, or ? if None."""
    if pct is None:
        return "?"
    return f"{pct:.0f}%"


def fmt_cost(usd: float) -> str:
    """Format cost: $0.42, $29.07."""
    if usd >= 100:
        return f"${usd:.0f}"
    return f"${usd:.2f}"


def fmt_duration(ms: int) -> str:
    """Format duration: 5s, 2m, 1h23m, 4h47m."""
    s = ms // 1000
    if s < 60:
        return f"{s}s"
    m = s // 60
    if m < 60:
        return f"{m}m"
    h = m // 60
    rm = m % 60
    return f"{h}h{rm:02d}m" if rm else f"{h}h"


def fmt_tokens(n: int) -> str:
    """Format token count: 1.2K, 1.2M, 847K."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}K"
    return f"{n / 1_000_000:.1f}M"


def fmt_rate_limit(pct: float, resets_at: int = 0) -> str:
    """Format rate limit percentage with optional countdown."""
    if resets_at > 0:
        import time
        remaining = max(0, resets_at - int(time.time()))
        if remaining > 0:
            return f"{pct:.0f}% ({fmt_duration(remaining * 1000)})"
    return f"{pct:.0f}%"


def fmt_lines(added: int, removed: int) -> str:
    """Format line counts: +123/-45."""
    parts = []
    if added:
        parts.append(f"+{added}")
    if removed:
        parts.append(f"-{removed}")
    return "/".join(parts) if parts else ""


# ── Icons ────────────────────────────────────────────────────────────

# NerdFont → emoji → ASCII fallback chains
_ICON_MAP = {
    "persona": ("", "🎭", "@"),
    "model": ("", "🤖", "M"),
    "context": ("", "📊", "C"),
    "cost": ("", "💰", "$"),
    "git_branch": ("", "🔀", "⎇"),
    "git_dirty": ("", "✏️", "*"),
    "time": ("", "⏱️", "T"),
    "memory": ("🧠", "🧠", "M"),
    "session": ("", "📋", "#"),
    "topic": ("", "📖", ">"),
    "rate": ("", "⚡", "R"),
    "cache": ("", "💾", "C"),
    "lines_add": ("", "✅", "+"),
    "lines_del": ("", "❌", "-"),
    "worktree": ("", "⚙️", "W"),
    "arrow_right": ("", "→", "->"),
    "heart": ("", "💓", "♥"),
    "telescope": ("", "🔭", "T"),
    "ship": ("", "🚢", "F"),
    "sparkle": ("", "✨", "*"),
}


def icon(name: str, use_nerd: bool = True, use_emoji: bool = True) -> str:
    """Get icon with fallback chain: NerdFont → emoji → ASCII."""
    entry = _ICON_MAP.get(name, ("?", "?", "?"))
    if use_nerd and entry[0]:
        return entry[0]
    if use_emoji and entry[1]:
        return entry[1]
    return entry[2]


# ── Text utilities ───────────────────────────────────────────────────

_ANSI_RE = re.compile(r"\033\[[0-9;]*[A-Za-z]")

# wcwidth is required for emoji-aware cell-width math but is OPTIONAL — if
# the runtime environment doesn't have it (e.g. uv-script ephemeral envs that
# don't declare it as a dep), fall back to naive len() so the statusline still
# renders. Width math will be slightly off for emojis but never crashes.
try:
    import wcwidth as _wcwidth
    _WCWIDTH_AVAILABLE = True
except ImportError:
    _wcwidth = None  # type: ignore[assignment]
    _WCWIDTH_AVAILABLE = False

# Hand-tuned compensation for emojis that some terminal fonts under/over-count.
# Most Alacritty / Kitty / iTerm setups treat these as double-width (2 cells).
# wcwidth's database may report 1 for some of them; force 2 here.
_EMOJI_WIDTH_OVERRIDES = {
    # Section glyphs. 💻 U+1F4BB LAPTOP COMPUTER replaced 🖥️ as the hardware
    # section glyph (VS-16 width drift risk); 🪷 is the default persona glyph.
    "💻": 2,
    "🪷": 2, "🖥️": 2, "🎮": 2, "🔧": 2, "📡": 2, "🔗": 2, "🌸": 2,
    # Persona glyphs registered in an optional claude-emoji DB (`persona:*`
    # category). VS-16-bearing entries explicitly forced to width=2 to prevent
    # off-by-one drift in the fixed-width identity cell. Refresh this set if
    # the registered persona glyphs change.
    "🧬": 2,
    "🪽": 2,    # Unicode 14, same font-availability risk class as 🪷
    "🏷️": 2,   # VS-16
    "🌲": 2,
    "🕸️": 2,   # VS-16
    "🌺": 2,
    "🧿": 2,
    "💼": 2,
    "📊": 2,
    "🧮": 2,
    "🍵": 2,
    "⎇": 1,    # branch glyph, single-width
    # Zero-width characters must be 0 even on the naive no-wcwidth fallback:
    # _zwc() inserts ZWSP to equalize char count and visible width, so counting
    # it as 1 un-pads every emoji-bearing cell and breaks grid pipe alignment.
    "​": 0,   # ZERO WIDTH SPACE
    "️": 0,   # VARIATION SELECTOR-16 (standalone; pairs are handled above)
}


def strip_ansi(text: str) -> str:
    """Remove all ANSI escape sequences from text."""
    return _ANSI_RE.sub("", text)


def visible_len(s: str) -> int:
    """Visible terminal-cell width of `s`, with ANSI stripped and emoji-aware."""
    stripped = strip_ansi(s)
    total = 0
    i = 0
    while i < len(stripped):
        ch = stripped[i]
        # Check 1-2 char compound emoji prefix (with variation selector)
        if i + 1 < len(stripped):
            pair = stripped[i : i + 2]
            if pair in _EMOJI_WIDTH_OVERRIDES:
                total += _EMOJI_WIDTH_OVERRIDES[pair]
                i += 2
                continue
        if ch in _EMOJI_WIDTH_OVERRIDES:
            total += _EMOJI_WIDTH_OVERRIDES[ch]
            i += 1
            continue
        if _WCWIDTH_AVAILABLE:
            w = _wcwidth.wcwidth(ch)  # type: ignore[union-attr]
            if w is None or w < 0:
                w = 1  # treat unknown as 1 cell
        else:
            w = 1  # naive fallback when wcwidth not installed
        total += w
        i += 1
    return total


def truncate(text: str, width: int, ellipsis: str = "…") -> str:
    """Truncate visible text to width, preserving ANSI codes."""
    if visible_len(text) <= width:
        return text
    # Strip ANSI, truncate, re-apply is lossy — just truncate plain
    plain = strip_ansi(text)
    return plain[: width - len(ellipsis)] + ellipsis


def pad_right(text: str, width: int) -> str:
    """Pad text to width, accounting for ANSI codes."""
    vis = visible_len(text)
    if vis >= width:
        return text
    return text + " " * (width - vis)


# ── Styled: visible-width-as-data ─────────────────────────────────────
#
# The pain `Styled` retires:
#   1. visible_len(s)          — compute width of a styled str (slow path)
#   2. _pad_visible / pad_right — pad a styled str to a target width
#   3. truncate(s, width)      — lossy clip of a styled str
#   4. _EMOJI_WIDTH_OVERRIDES  — hand-tuned wcwidth fixes
#   5. _ANSI_RE / strip_ansi   — peel ANSI to re-count cells
#
# By carrying `visible_width` AS A FIELD next to the styled string, callers
# stop recomputing visible_len on every layout pass. The width is established
# once at construction (by `Styled.from_text(...)` or via `colors.styled_w`)
# and propagates correctly through __add__ / .padded() / .truncated().
#
# Stage 1 lands the TYPE. Callers continue to use raw `str` + the legacy
# helpers; opt-in migration is a future change.


def _truncate_visible(plain: str, max_width: int) -> str:
    """Truncate `plain` (ANSI-free) to at most `max_width` visible cells.

    Walks the string cell-by-cell using the same width logic as `visible_len`
    so wide-char/emoji boundaries are respected. Never splits a wide-char in
    half. Returns empty string if `max_width` <= 0.
    """
    if max_width <= 0:
        return ""
    total = 0
    out: list[str] = []
    i = 0
    while i < len(plain):
        ch = plain[i]
        # Compound emoji + variation selector (2-char prefix in override table)
        if i + 1 < len(plain):
            pair = plain[i : i + 2]
            if pair in _EMOJI_WIDTH_OVERRIDES:
                w = _EMOJI_WIDTH_OVERRIDES[pair]
                if total + w > max_width:
                    break
                out.append(pair)
                total += w
                i += 2
                continue
        if ch in _EMOJI_WIDTH_OVERRIDES:
            w = _EMOJI_WIDTH_OVERRIDES[ch]
            if total + w > max_width:
                break
            out.append(ch)
            total += w
            i += 1
            continue
        if _WCWIDTH_AVAILABLE:
            w = _wcwidth.wcwidth(ch)  # type: ignore[union-attr]
            if w is None or w < 0:
                w = 1
        else:
            w = 1
        if total + w > max_width:
            break
        out.append(ch)
        total += w
        i += 1
    return "".join(out)


@dataclass(frozen=True)
class Styled:
    """A styled text fragment that carries its visible cell-width as data.

    `text` may contain ANSI escape sequences.
    `visible_width` is the number of terminal cells the text occupies when
    rendered to a UTF-8 terminal supporting wide characters.

    Compose with __add__:    Styled("a", 1) + Styled("b", 1)  →  Styled("ab", 2)
    Mix with raw str:        Styled("x", 1) + " "             →  Styled("x ", 2)
    Pad / align:             a.padded(10, "right")            →  pad + a
    Truncate (lossy ANSI):   a.truncated(3)                   →  width-aware cut

    Replaces the visible_len + pad_right + truncate + emoji-overrides cluster
    when callers can construct width at the source. Stage-1 type — Stage-2
    will add an opt-in `colors.styled_w()` constructor; callers stay on raw
    `str` until they migrate explicitly.
    """

    text: str
    visible_width: int

    def __post_init__(self) -> None:
        if self.visible_width < 0:
            raise ValueError(
                f"Styled.visible_width must be >= 0, got {self.visible_width}"
            )

    @classmethod
    def from_text(cls, text: str) -> "Styled":
        """Construct from raw text by computing visible_width once (slow path).

        Use this for one-off conversions of legacy `str` content into Styled.
        Prefer constructing with a known width whenever possible — the whole
        point of `Styled` is to compute the width ONCE, at the source.
        """
        return cls(text, visible_len(text))

    @classmethod
    def empty(cls) -> "Styled":
        """The zero-width empty fragment. Useful as `__add__` identity."""
        return cls("", 0)

    def __add__(self, other: "str | Styled") -> "Styled":
        if isinstance(other, Styled):
            return Styled(self.text + other.text, self.visible_width + other.visible_width)
        if isinstance(other, str):
            # Compute width of the raw str on the fly (slow path). Callers
            # paying the visible_len cost in __add__ get exactly the same
            # bill they paid before; the point of Styled is that *frequent*
            # widths come pre-computed.
            return Styled(self.text + other, self.visible_width + visible_len(other))
        return NotImplemented  # type: ignore[return-value]

    def __radd__(self, other: "str | Styled") -> "Styled":
        if isinstance(other, str):
            return Styled(other + self.text, visible_len(other) + self.visible_width)
        if isinstance(other, Styled):  # unreachable but documents intent
            return Styled(other.text + self.text, other.visible_width + self.visible_width)
        return NotImplemented  # type: ignore[return-value]

    def __str__(self) -> str:
        """Allow Styled to flow through f-strings and join() transparently."""
        return self.text

    def __len__(self) -> int:
        """The Pythonic answer: `len()` returns visible_width, not byte length.

        Layout code reaches for `len()` constantly. Returning `visible_width`
        here means the grid renderer's `len(cell.content)` Just Works without
        a special case.
        """
        return self.visible_width

    def padded(self, target_width: int, align: str = "left") -> "Styled":
        """Pad to `target_width` visible cells with align L/R/C. No-op if wider."""
        if self.visible_width >= target_width:
            return self
        diff = target_width - self.visible_width
        if align == "right":
            return Styled(" " * diff + self.text, target_width)
        if align == "center":
            left = diff // 2
            right = diff - left
            return Styled(" " * left + self.text + " " * right, target_width)
        return Styled(self.text + " " * diff, target_width)

    def truncated(self, max_width: int, ellipsis: str = "…") -> "Styled":
        """Truncate to `max_width` visible cells; append ellipsis if anything cut.

        LOSSY w.r.t. ANSI: strips escape sequences before truncating, then
        re-runs through `visible_len` to compute the final width. ANSI-aware
        truncation that preserves color escapes is a future improvement.
        """
        if self.visible_width <= max_width:
            return self
        if max_width <= 0:
            return Styled.empty()
        plain = strip_ansi(self.text)
        ell_width = visible_len(ellipsis)
        if max_width <= ell_width:
            # Not enough room for the ellipsis itself — emit just the prefix.
            return Styled(_truncate_visible(plain, max_width), max_width)
        prefix = _truncate_visible(plain, max_width - ell_width)
        result = prefix + ellipsis
        return Styled(result, visible_len(result))
