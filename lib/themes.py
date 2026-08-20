"""Theme definitions for claude-statusline.

Each theme composes primitives + colors into a multi-line statusline string.
Themes never touch raw payloads — they only read ComponentData dicts.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from colors import ColorPalette, RST, BOLD, DIM, fg, bg, styled, get_palette, resolve_persona_color
from primitives import (
    progress_bar, sparkline, sep, powerline_sep,
    fmt_pct, fmt_cost, fmt_duration, fmt_tokens, fmt_rate_limit, fmt_lines,
    icon, strip_ansi, visible_len, truncate, pad_right,
)
from components import ComponentData
from layout_grid import Column, Cell, Row, Grid


# ── Helpers ──────────────────────────────────────────────────────────


def _v(components: Dict[str, ComponentData], name: str) -> Optional[ComponentData]:
    """Get a component if present and error-free."""
    c = components.get(name)
    if c and not c.error:
        return c
    return None


def _typed(components: Dict[str, ComponentData], name: str) -> Optional[dict]:
    """Get a component's value dict if present and error-free.

    Callers access keys directly on the returned dict. TypedDict annotations
    on compute_* return values provide type safety at check time.

    Usage:
        ctx = _typed(components, "context")
        pct = ctx["used_percentage"] if ctx else None
    """
    c = components.get(name)
    if c and not c.error:
        return c.value
    return None


def _identity_tag(components: Dict[str, ComponentData], palette: ColorPalette) -> str:
    """Render [persona:N] tag, color-coded by persona role if available."""
    c = _v(components, "identity")
    if not c:
        return styled("[?]", palette.fg_dim)
    persona = c.value.get("persona", "claude")
    num = c.value.get("session_number", 0)
    if num:
        tag = f"[{persona}:{num}]"
    else:
        tag = f"[{persona}]"

    # Use persona-specific color if available, fall back to palette accent
    color = palette.accent
    persona_c = _v(components, "persona")
    if persona_c:
        persona_hex = resolve_persona_color(persona_c.value.get("color", ""))
        if persona_hex:
            color = persona_hex

    return styled(tag, color, bold=True)


def _context_segment(components: Dict[str, ComponentData], palette: ColorPalette,
                     bar_width: int = 12) -> str:
    """Render ctx:42% ████████░░░░."""
    ctx = _typed(components, "context")
    pct = ctx["used_percentage"] if ctx else None
    label = styled("ctx:", palette.fg_dim)
    pct_str = styled(fmt_pct(pct), palette.info)
    bar = progress_bar(pct, width=bar_width, fill_color=palette.info, empty_color=palette.fg_dim)
    return f"{label}{pct_str} {bar}"


def _cost_str(components: Dict[str, ComponentData], palette: ColorPalette) -> str:
    """Render $29.07."""
    cost = _typed(components, "cost")
    return styled(fmt_cost(cost["total_cost_usd"] if cost else 0.0), palette.warn)


def _duration_str(components: Dict[str, ComponentData], palette: ColorPalette,
                  show_api: bool = False) -> str:
    """Render 4h47m or 4h47m (api:1h14m)."""
    dur = _typed(components, "duration")
    cost = _typed(components, "cost")
    total = (dur["total_ms"] if dur else None) or (cost["total_duration_ms"] if cost else 0)
    api = (dur["api_ms"] if dur else None) or (cost["total_api_duration_ms"] if cost else 0)
    s = styled(fmt_duration(total), palette.fg)
    if show_api and api is not None and api > 0:
        s += styled(f" (api:{fmt_duration(api)})", palette.fg_dim)
    return s


def _topic_chain(components: Dict[str, ComponentData], palette: ColorPalette) -> str:
    """Render auth -> db -> api."""
    c = _v(components, "topics")
    if not c:
        return styled("no topics", palette.fg_dim)
    history = c.value.get("history", [])
    if not history:
        return styled("no topics", palette.fg_dim)
    arrow = styled(" \u2192 ", palette.fg_dim)
    parts = [styled(t, palette.info) for t in history]
    return arrow.join(parts)


def _git_segment(components: Dict[str, ComponentData], palette: ColorPalette) -> str:
    """Render  main* +3/-1."""
    c = _v(components, "git")
    if not c or not c.value.get("is_repo"):
        return styled("no repo", palette.fg_dim)
    v = c.value
    branch = v.get("branch", "?")
    dirty = "*" if v.get("dirty") else ""
    ahead = v.get("ahead", 0)
    behind = v.get("behind", 0)

    parts = [styled(f"{icon('git_branch')} {branch}{dirty}", palette.ok)]
    if ahead:
        parts.append(styled(f" \u2191{ahead}", palette.info))
    if behind:
        parts.append(styled(f" \u2193{behind}", palette.warn))
    return "".join(parts)


def _lines_segment(components: Dict[str, ComponentData], palette: ColorPalette) -> str:
    """Render +6641/-80."""
    lines = _typed(components, "lines")
    added = lines["added"] if lines else 0
    removed = lines["removed"] if lines else 0
    s = fmt_lines(added, removed)
    if not s:
        return styled("\u00b10", palette.fg_dim)
    return styled(s, palette.ok)


def _rate_limits_segment(components: Dict[str, ComponentData], palette: ColorPalette,
                         bar_width: int = 8) -> str:
    """Render 5h:15% ████░░░░ │ 7d:2% █░░░░░░░."""
    c = _v(components, "rate_limits")
    if not c:
        return styled("rates:?", palette.fg_dim)
    v = c.value
    five_pct = v.get("five_hour_pct", 0.0)
    seven_pct = v.get("seven_day_pct", 0.0)

    five_color = palette.warn if five_pct > 50 else palette.ok
    seven_color = palette.warn if seven_pct > 50 else palette.ok

    five = (styled("5h:", palette.fg_dim) +
            styled(fmt_pct(five_pct), five_color) + " " +
            progress_bar(five_pct, width=bar_width, fill_color=five_color, empty_color=palette.fg_dim))
    seven = (styled("7d:", palette.fg_dim) +
             styled(fmt_pct(seven_pct), seven_color) + " " +
             progress_bar(seven_pct, width=bar_width, fill_color=seven_color, empty_color=palette.fg_dim))
    return five + sep(palette.separator) + seven


def _cache_segment(components: Dict[str, ComponentData], palette: ColorPalette) -> str:
    """Render cache C:5.0K R:2.0K."""
    c = _v(components, "cache_stats")
    if not c:
        return styled("cache:?", palette.fg_dim)
    creation = c.value.get("creation_tokens", 0)
    read = c.value.get("read_tokens", 0)
    return (styled("cache ", palette.fg_dim) +
            styled(f"C:{fmt_tokens(creation)}", palette.info) + " " +
            styled(f"R:{fmt_tokens(read)}", palette.accent))


def _memory_segment(components: Dict[str, ComponentData], palette: ColorPalette) -> str:
    """Render 🧠 H:10.9K K:411K J:29 L:4 M:847K F:51 S:242."""
    c = _v(components, "memory")
    if not c:
        return styled("mem:?", palette.fg_dim)
    v = c.value

    def _fmt(val):
        if val == "?" or val is None:
            return "?"
        if isinstance(val, (int, float)):
            return fmt_tokens(int(val))
        return str(val)

    return (icon("memory") + " " +
            styled(f"H:{_fmt(v.get('hippo'))}", palette.info) + " " +
            styled(f"K:{_fmt(v.get('koi'))}", palette.accent) + " " +
            styled(f"J:{_fmt(v.get('journal'))}", palette.ok) + " " +
            styled(f"L:{_fmt(v.get('letta'))}", palette.warn) + " " +
            styled(f"M:{_fmt(v.get('messages'))}", palette.info) + " " +
            styled(f"F:{_fmt(v.get('files'))}", palette.fg) + " " +
            styled(f"S:{_fmt(v.get('sessions'))}", palette.fg))


# ── Base class ───────────────────────────────────────────────────────


class Theme(ABC):
    name: str
    lines: int
    default_color_scheme: str

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Skip validation for abstract subclasses
        if getattr(cls, '__abstractmethods__', None):
            return
        for attr in ('name', 'lines', 'default_color_scheme'):
            if not hasattr(cls, attr):
                raise TypeError(
                    f"Theme subclass {cls.__name__} must define class attribute '{attr}'"
                )

    @abstractmethod
    def required_components(self) -> List[str]:
        ...

    @abstractmethod
    def render(self, components: Dict[str, ComponentData], palette: ColorPalette) -> str:
        ...


# ── Classic rendering (shared by ClassicTheme + GpuTheme) ───────────


def _render_classic_lines(components: Dict[str, ComponentData], palette: ColorPalette) -> str:
    """Render the standard 2-line Classic layout.

    Line 1: [persona:N] Model │ ctx:42% ████████░░░░ │ $29.07 │ 5h:15% │ 7d:2%
    Line 2: ~/path │ v2.1.37 │ explanatory │ 4h47m │ +6641/-80

    Extracted as a helper so Classic and GPU themes stay in sync.
    """
    s = sep(palette.separator)

    # Identity
    tag = _identity_tag(components, palette)

    # Session title (if inferred)
    identity = _typed(components, "identity")
    title = identity["session_title"] if identity else ""
    if title:
        tag = tag + " " + styled(title, palette.fg_dim)

    # Model
    model = _typed(components, "model")
    model_name = (model["display_name"] if model else None) or (model["id"] if model else None) or "?"
    model_str = styled(model_name, palette.info)

    # Context with semantic coloring
    ctx = _typed(components, "context")
    ctx_pct = ctx["used_percentage"] if ctx else None
    if ctx_pct is None:
        ctx_hex = palette.fg_dim
    elif ctx_pct < 50:
        ctx_hex = palette.ok
    elif ctx_pct < 80:
        ctx_hex = palette.warn
    else:
        ctx_hex = palette.error
    ctx_label = styled(f"ctx:{fmt_pct(ctx_pct)}", ctx_hex)
    ctx_bar = progress_bar(ctx_pct, width=12, fill_color=ctx_hex, empty_color=palette.separator)

    # Cost
    cost = _typed(components, "cost")
    cost_usd = cost["total_cost_usd"] if cost else 0.0
    cost_str = styled(fmt_cost(cost_usd), palette.ok)

    # Rate limits (inline, not with bars)
    rate_parts: list[str] = []
    rl = _typed(components, "rate_limits")
    five_pct = rl["five_hour_pct"] if rl else 0.0
    seven_pct = rl["seven_day_pct"] if rl else 0.0
    if five_pct and five_pct > 0:
        five_color = palette.ok if five_pct < 50 else (palette.warn if five_pct < 80 else palette.error)
        rate_parts.append(styled(f"5h:{five_pct:.0f}%", five_color))
    # 7d quota is the strategic budget — always render, even at 0%, so it's
    # visible all week and never silently absent. (5h stays conditional —
    # it's noisy at 0% during idle stretches.)
    seven_pct_safe = seven_pct or 0.0
    seven_color = palette.ok if seven_pct_safe < 50 else (palette.warn if seven_pct_safe < 80 else palette.error)
    rate_parts.append(styled(f"7d:{seven_pct_safe:.0f}%", seven_color))

    # Line 1
    line1_parts = [tag, model_str, f"{ctx_label} {ctx_bar}", cost_str]
    if rate_parts:
        line1_parts.extend(rate_parts)
    line1 = s.join(line1_parts)

    # Worktree indicator
    wt = _v(components, "worktree")
    if wt and wt.value.get("active"):
        wt_str = styled(f"⚙ {wt.value.get('name', '?')}", palette.warn)
        line1 = f"{wt_str}{s}{line1}"

    # Line 2: path │ version │ output_style │ duration │ +lines/-lines
    ws = _typed(components, "workspace")
    cwd = ws["cwd_short"] if ws else "?"
    ver_data = _typed(components, "version")
    ver = ver_data["version"] if ver_data else ""
    output_style = ws["output_style"] if ws else "default"
    dur = _typed(components, "duration")
    cost_d = _typed(components, "cost")
    dur_ms = (dur["total_ms"] if dur else None) or (cost_d["total_duration_ms"] if cost_d else 0)
    lines_d = _typed(components, "lines")
    added = (lines_d["added"] if lines_d else 0) or 0
    removed = (lines_d["removed"] if lines_d else 0) or 0

    line2_parts: list[str] = [styled(cwd, palette.fg_dim)]
    if ver:
        line2_parts.append(styled(f"v{ver}", palette.fg_dim))
    if output_style and output_style != "default":
        line2_parts.append(styled(output_style, palette.fg_dim))
    if dur_ms:
        line2_parts.append(styled(fmt_duration(dur_ms), palette.fg_dim))
    if added or removed:
        line2_parts.append(
            styled(f"+{added}", palette.ok) + styled(f"/-{removed}", palette.error)
        )
    line2 = s.join(line2_parts)

    return f"{line1}\n{line2}"


# ── 0. Classic (2 lines) — Phase 1 original ───────────────────────────


class ClassicTheme(Theme):
    """The original Phase 1 statusline — the one that was live before themes existed."""
    name = "classic"
    lines = 2
    default_color_scheme = "catppuccin_mocha"

    def required_components(self) -> List[str]:
        return [
            "identity", "persona", "context", "cost", "model", "rate_limits",
            "workspace", "version", "duration", "lines", "worktree",
        ]

    def render(self, components: Dict[str, ComponentData], palette: ColorPalette) -> str:
        return _render_classic_lines(components, palette)


# ── 0b. Hardware (5 lines) — minimal dashboard on a wide-c1 grid ──────
#
# hw has its OWN 6-column grid (not the gpu 8-col grid) with a first column
# wide enough that the CPU/GPU/iface/persona NAME fits in a SINGLE cell (no
# 2-column span, no truncation). Every '│' still lands on a shared boundary,
# so rows align. Multi-cell fields (path span 3, branch span 2) are centred.
# Empty trailing cells are left BLANK — hw uses no em-dashes.

_HW_COLUMNS: List[Column] = [
    Column("c1", width=28, align="left"),    # name / persona@host / iface / path
    Column("c2", width=24, align="left"),    # model / CPU|GPU bar / ↓rate
    Column("c3", width=22, align="left"),    # ctx bar / RAM|VRAM bar / ↑rate
    Column("c4", width=16, align="center"),  # cost / mem GB / ↓total
    Column("c5", width=16, align="center"),  # rate limits / temp / ↑total
    Column("c6", width=14, align="right"),   # version / (blank) / signal
]
_HW_GRID = Grid(columns=_HW_COLUMNS, separator=" │ ")


class HardwareTheme(Theme):
    """Minimal 5-line hardware dashboard on its own wide-first-column grid.

    L1 identity | model | ctx | $ | rates | version
    L2 path (span 2) | full session id (span 2) | branch | diff
    L3 CPU | CPU% | RAM%  | RAM GB  | temp
    L4 GPU | GPU% | VRAM% | VRAM GB | temp
    L5 wifi | ↓rate | ↑rate | ↓total | ↑total | signal
    Vitals only: no power/clock/fan, no per-process rows, no tailscale. Names
    fit a single cell; empty cells are blank (no em-dashes).
    """
    name = "hw"
    lines = 5
    default_color_scheme = "catppuccin_mocha"

    def required_components(self) -> List[str]:
        return [
            "identity", "persona", "model", "context", "cost", "rate_limits",
            "version", "workspace", "git", "lines", "cpu", "gpu", "net",
        ]

    def render(self, components: Dict[str, ComponentData], palette: ColorPalette) -> str:
        rows = [
            self._row_identity(components, palette),
            self._row_workspace(components, palette),
            self._row_cpu(components, palette),
            self._row_gpu(components, palette),
            self._row_net(components, palette),
        ]
        return "\n".join(_HW_GRID.render(r) for r in rows)

    def _row_identity(self, components, palette) -> Row:
        iv = _v(components, "identity")
        persona = (iv.value.get("persona", "claude") if iv else "claude") or "claude"
        host = (iv.value.get("host", "") if iv else "") or ""
        num = iv.value.get("session_number", 0) if iv else 0
        picon = ((iv.value.get("persona_icon", "") if iv else "") or "🪷")
        color = palette.accent
        pc = _v(components, "persona")
        if pc:
            ph = resolve_persona_color(pc.value.get("color", ""))
            if ph:
                color = ph
        who = f"{persona}@{host}" if host else persona
        if num:
            who = f"{who}:{num}"
        id_cell = _zwc(styled(f"{picon}  ", color, bold=True) + styled(who, color, bold=True))
        model = _typed(components, "model") or {}
        model_cell = styled(model.get("display_name") or model.get("id") or "?", palette.info)
        ctx_cell = _context_segment(components, palette)
        cost_cell = styled(fmt_cost((_typed(components, "cost") or {}).get("total_cost_usd", 0.0)), palette.ok)
        rl = _typed(components, "rate_limits") or {}
        five = rl.get("five_hour_pct", 0) or 0
        seven = rl.get("seven_day_pct", 0) or 0
        rate_parts: List[str] = []
        if five > 0:
            rate_parts.append(styled(f"5h:{five:.0f}%", _rate_color(five, palette)))
        rate_parts.append(styled(f"7d:{seven:.0f}%", _rate_color(seven, palette)))
        rates_cell = " ".join(rate_parts)
        ver = (_typed(components, "version") or {}).get("version", "")
        ver_cell = styled(f"v{ver}", palette.fg_dim) if ver else ""
        return _HW_GRID.row(cells=[
            Cell(content=id_cell, span=1, align="left"),
            Cell(content=model_cell, span=1, align="left"),
            Cell(content=ctx_cell, span=1, align="left"),
            Cell(content=cost_cell, span=1, align="center"),
            Cell(content=rates_cell, span=1, align="center"),
            Cell(content=ver_cell, span=1, align="right"),
        ])

    def _row_workspace(self, components, palette) -> Row:
        """Line 2: path (span 2) | full session id (span 2) | branch | diff.

        The session id renders IN FULL (36-char UUID) — it exists to be
        copy-pasted into `claude --resume` / fleet tooling, and a clipped
        id is useless for that. The c3-c4 span is 41 visible chars, so the
        UUID fits with room; branch takes the c5 squeeze instead, using the
        middle-ellipsis _truncate_branch so both ends stay identifiable.
        """
        ws = _typed(components, "workspace") or {}
        cwd = ws.get("cwd_short") or ws.get("cwd") or "?"
        git_d = _typed(components, "git") or {}
        branch = git_d.get("branch", "") or ""
        if branch == "?":
            branch = ""
        ld = _typed(components, "lines") or {}
        added = ld.get("added", 0) or 0
        removed = ld.get("removed", 0) or 0

        # Full session id — same fallback chain as _row_identity, pure
        # string reads only (session_id_full is shell-resolved upstream).
        ident = _v(components, "identity")
        iv = ident.value if ident else {}
        sid = iv.get("session_id_full", "") or iv.get("session_id", "") or ""
        if not sid:
            tpath = iv.get("transcript_path", "") or ""
            if tpath:
                base = tpath.rsplit("/", 1)[-1]
                if base.endswith(".jsonl"):
                    base = base[:-6]
                sid = base

        path_cell = styled(cwd, palette.fg_dim)
        sid_cell = styled(sid, palette.fg_dim) if sid else ""
        branch_cell = (styled(f"⎇ {_truncate_branch(branch, 16)}", palette.info)
                       if branch else "")
        diff_cell = (styled(f"+{added}", palette.ok) + styled(f"/-{removed}", palette.error)
                     if (added or removed) else "")
        return _HW_GRID.row(cells=[
            Cell(content=path_cell, span=2, align="left"),      # c1-c2 path
            Cell(content=sid_cell, span=2, align="left"),       # c3-c4 full session id
            Cell(content=branch_cell, span=1, align="left"),    # c5 branch
            Cell(content=diff_cell, span=1, align="right"),     # c6 diff
        ])

    def _row_cpu(self, components, palette) -> Row:
        cpu = _v(components, "cpu")
        if not cpu or not cpu.value.get("available"):
            return _HW_GRID.row(cells=[
                Cell(content=styled("💻  CPU: not available", palette.fg_dim),
                     span=len(_HW_COLUMNS))])
        cv = cpu.value
        chip = _zwc(styled("💻  ", palette.accent) +
                    styled(cv.get("name", "CPU"), palette.accent, bold=True))
        return _HW_GRID.row(cells=[
            Cell(content=chip, span=1, align="left"),                                  # c1 name (single cell)
            Cell(content=_gpu_bar(cv.get("cpu_pct", 0.0), "CPU", palette, bar_width=10),
                 span=1, align="left"),                                                # c2 CPU% bar
            Cell(content=_gpu_bar(cv.get("ram_pct", 0.0), "RAM", palette, bar_width=10),
                 span=1, align="left"),                                                # c3 RAM% bar
            Cell(content=styled(_fmt_gb(cv.get("ram_used_mib", 0),
                                        cv.get("ram_total_mib", 0)).strip(), palette.fg_dim),
                 span=1, align="center"),                                              # c4 RAM GB
            Cell(content=_cpu_temp(cv.get("temp_c", 0), cv.get("high_c", 0),
                                   cv.get("critical_c", 0), palette),
                 span=1, align="center"),                                              # c5 temp
            Cell(content="", span=1, align="right"),                                   # c6 blank
        ])

    def _row_gpu(self, components, palette) -> Row:
        gpu = _v(components, "gpu")
        if not gpu or not gpu.value.get("available"):
            return _HW_GRID.row(cells=[
                Cell(content=styled("🎮  GPU: not available", palette.fg_dim),
                     span=len(_HW_COLUMNS))])
        gv = gpu.value
        mem_used = gv.get("mem_used_mib", 0)
        mem_total = gv.get("mem_total_mib", 0)
        vram_pct = (mem_used / mem_total * 100) if mem_total > 0 else 0
        chip = _zwc(styled("🎮  ", palette.accent) +
                    styled(gv.get("name", "GPU"), palette.accent, bold=True))
        return _HW_GRID.row(cells=[
            Cell(content=chip, span=1, align="left"),                                  # c1 name (single cell)
            Cell(content=_gpu_bar(gv.get("gpu_util", 0), "GPU", palette, bar_width=10),
                 span=1, align="left"),                                                # c2 GPU% bar
            Cell(content=_gpu_bar(vram_pct, "VRAM", palette, bar_width=10),
                 span=1, align="left"),                                                # c3 VRAM% bar
            Cell(content=styled(_fmt_gb(mem_used, mem_total).strip(), palette.fg_dim),
                 span=1, align="center"),                                              # c4 VRAM GB
            Cell(content=_gpu_temp(gv.get("temp_c", 0), palette),
                 span=1, align="center"),                                              # c5 temp
            Cell(content="", span=1, align="right"),                                   # c6 blank
        ])

    def _row_net(self, components, palette) -> Row:
        net = _v(components, "net")
        if not net or not net.value.get("available"):
            return _HW_GRID.row(cells=[
                Cell(content=styled("📡  wifi: not available", palette.fg_dim),
                     span=len(_HW_COLUMNS))])
        nv = net.value
        iface = nv.get("iface", "?")
        ssid = nv.get("ssid", "")
        label = f"{iface}/{ssid}" if ssid else iface
        iface_cell = _zwc(styled(f"📡  {label}", palette.accent, bold=True))
        sig = nv.get("signal_dbm")
        sig_cell = (styled(f"{sig} dBm", _severity_color(float(sig), -70, -85, palette, inverse=True))
                    if sig is not None else "")
        return _HW_GRID.row(cells=[
            Cell(content=iface_cell, span=1, align="left"),                            # c1 iface
            Cell(content=styled(f"↓ {_fmt_bps(nv.get('down_bps', 0))}", palette.info),
                 span=1, align="left"),                                                # c2 ↓rate
            Cell(content=styled(f"↑ {_fmt_bps(nv.get('up_bps', 0))}", palette.info),
                 span=1, align="left"),                                                # c3 ↑rate
            Cell(content=styled(f"{_fmt_bytes(nv.get('total_down_bytes', 0))} ↓", palette.fg_dim),
                 span=1, align="center"),                                              # c4 ↓total
            Cell(content=styled(f"{_fmt_bytes(nv.get('total_up_bytes', 0))} ↑", palette.fg_dim),
                 span=1, align="center"),                                              # c5 ↑total
            Cell(content=sig_cell, span=1, align="right"),                             # c6 signal
        ])


# ── 1. Observatory (3 lines) ────────────────────────────────────────


class ObservatoryTheme(Theme):
    name = "observatory"
    lines = 3
    default_color_scheme = "catppuccin_mocha"

    def required_components(self) -> List[str]:
        return [
            "identity", "persona", "context", "cost", "model", "duration", "lines",
            "version", "rate_limits", "cache_stats", "worktree", "workspace",
            "git", "topics", "sessions", "memory",
        ]

    def render(self, components: Dict[str, ComponentData], palette: ColorPalette) -> str:
        s = sep(palette.separator)

        # Line 1: [persona:N] Model │ ctx:42% ████████░░░░ │ $29.07 │ 5h:15% 7d:2%
        model = _typed(components, "model")
        model_name = model["display_name"] if model else "?"
        line1 = (
            _identity_tag(components, palette) + " " +
            styled(model_name, palette.fg, bold=True) +
            s + _context_segment(components, palette) +
            s + _cost_str(components, palette) +
            s + _rate_limits_segment(components, palette)
        )

        # Line 2: ~/path │ main* +3/-1 │ +6641/-80 │ cache:C:5K R:2K │ 🧠 H:10K K:411K
        ws = _typed(components, "workspace")
        cwd = ws["cwd_short"] if ws else "?"
        git_str = _git_segment(components, palette)
        line2 = (styled(cwd, palette.fg) + s +
                 git_str + s +
                 _lines_segment(components, palette) + s +
                 _cache_segment(components, palette) + s +
                 _memory_segment(components, palette))

        # Line 3: v2.1.37 │ explanatory │ 4h47m (api:1h14m) │ Topics: auth → db → api
        ver_data = _typed(components, "version")
        ver = ver_data["version"] if ver_data else "?"
        ws3 = _typed(components, "workspace")
        output_style = ws3["output_style"] if ws3 else "?"
        line3 = (styled(f"v{ver}", palette.fg_dim) + s +
                 styled(output_style, palette.fg_dim) + s +
                 _duration_str(components, palette, show_api=True) + s +
                 styled("Topics: ", palette.fg_dim) + _topic_chain(components, palette))

        return f"{line1}\n{line2}\n{line3}"


# ── 1. Zen (1 line) ─────────────────────────────────────────────────


class ZenTheme(Theme):
    name = "zen"
    lines = 1
    default_color_scheme = "nord_frost"

    def required_components(self) -> List[str]:
        return ["identity", "persona", "context"]

    def render(self, components: Dict[str, ComponentData], palette: ColorPalette) -> str:
        tag = _identity_tag(components, palette)
        ctx = _typed(components, "context")
        pct = ctx["used_percentage"] if ctx else None
        bar = progress_bar(pct, width=24, fill_color=palette.info, empty_color=palette.fg_dim)
        pct_str = styled(fmt_pct(pct), palette.info)
        return f"{tag} {bar} {pct_str}"


# ── 2. Narrative (2 lines) ──────────────────────────────────────────


class NarrativeTheme(Theme):
    name = "narrative"
    lines = 2
    default_color_scheme = "solarized_light"

    def required_components(self) -> List[str]:
        return ["identity", "persona", "topics", "context", "cost"]

    def render(self, components: Dict[str, ComponentData], palette: ColorPalette) -> str:
        s = sep(palette.separator)

        # Line 1: [matt:3] auth → database → API → testing
        line1 = _identity_tag(components, palette) + " " + _topic_chain(components, palette)

        # Line 2: ctx:42% ████████░░░░ │ $29.07 │ 4h47m
        line2 = _context_segment(components, palette) + s + _cost_str(components, palette) + s + _duration_str(components, palette)

        return f"{line1}\n{line2}"


# ── 3. Fleet (2 lines) ──────────────────────────────────────────────


class FleetTheme(Theme):
    name = "fleet"
    lines = 2
    default_color_scheme = "catppuccin_latte"

    def required_components(self) -> List[str]:
        return ["identity", "persona", "sessions", "context"]

    def render(self, components: Dict[str, ComponentData], palette: ColorPalette) -> str:
        s = sep(palette.separator)

        # Line 1: [matt:3] Title │ ctx:42% ████░░░░ │ $29.07
        ident = _identity_tag(components, palette)
        identity = _typed(components, "identity")
        title = identity["session_title"] if identity else ""
        if title:
            ident = ident + " " + styled(title, palette.fg_dim)
        line1 = (ident + " " +
                 _context_segment(components, palette, bar_width=8) + s +
                 _cost_str(components, palette))

        # Line 2: Sessions: matt:1 (opus,$4) matt:2 (sonnet,$0.4) ...
        sess_c = _v(components, "sessions")
        if sess_c and sess_c.value.get("active"):
            sessions = sess_c.value["active"]
            sess_parts = []
            for key, info in sessions.items():
                if isinstance(info, dict):
                    model = info.get("model", "?")
                    cost = info.get("cost", 0.0)
                    sess_parts.append(styled(f"{key}", palette.info) +
                                      styled(f" ({model},{fmt_cost(cost)})", palette.fg_dim))
                else:
                    sess_parts.append(styled(str(key), palette.info))
            line2 = styled("Sessions: ", palette.fg_dim) + "  ".join(sess_parts)
        else:
            sess_typed = _typed(components, "sessions")
            count = sess_typed["count"] if sess_typed else 0
            line2 = styled(f"Sessions: {count} active", palette.fg_dim)

        return f"{line1}\n{line2}"


# ── 4. Memory Palace (2 lines) ──────────────────────────────────────


class MemoryPalaceTheme(Theme):
    name = "memory_palace"
    lines = 2
    default_color_scheme = "catppuccin_mocha"

    def required_components(self) -> List[str]:
        return ["identity", "persona", "memory", "context", "cost"]

    def render(self, components: Dict[str, ComponentData], palette: ColorPalette) -> str:
        s = sep(palette.separator)

        # Line 1: [matt:3] 🧠 H:10.9K K:411K J:29 L:4 M:847K F:51 S:242
        line1 = _identity_tag(components, palette) + " " + _memory_segment(components, palette)

        # Line 2: ctx:42% ████████░░░░ │ $29.07 │ total: 1.3M memories
        mem = _typed(components, "memory")
        total = mem["total"] if mem else "?"
        if isinstance(total, (int, float)):
            total_str = fmt_tokens(int(total))
        else:
            total_str = str(total)
        line2 = (_context_segment(components, palette) + s +
                 _cost_str(components, palette) + s +
                 styled(f"total: {total_str} memories", palette.accent))

        return f"{line1}\n{line2}"


# ── 5. Economics (2 lines) ──────────────────────────────────────────


class EconomicsTheme(Theme):
    name = "economics"
    lines = 2
    default_color_scheme = "catppuccin_mocha"

    def required_components(self) -> List[str]:
        return ["identity", "persona", "cost", "duration", "context", "lines"]

    def render(self, components: Dict[str, ComponentData], palette: ColorPalette) -> str:
        s = sep(palette.separator)

        # Line 1: [matt:3] $29.07 │ $6.12/hr │ +6641/-80 lines
        cost = _typed(components, "cost")
        cost_usd = cost["total_cost_usd"] if cost else 0.0
        burn_rate = cost["burn_rate"] if cost else 0.0
        lines_d = _typed(components, "lines")
        added = (lines_d["added"] if lines_d else 0) or 0
        removed = (lines_d["removed"] if lines_d else 0) or 0
        lines_str = fmt_lines(added, removed)

        line1 = (_identity_tag(components, palette) + " " +
                 styled(fmt_cost(cost_usd), palette.warn, bold=True) + s +
                 styled(f"{fmt_cost(burn_rate)}/hr", palette.warn) + s +
                 styled(f"{lines_str} lines" if lines_str else "\u00b10 lines", palette.ok))

        # Line 2: ctx:42% ████████░░░░ │ 4h47m (api:1h14m) │ $0.0044/line
        total_lines = int(added) + int(removed)
        cost_per_line = float(cost_usd or 0) / total_lines if total_lines > 0 else 0.0
        line2 = (_context_segment(components, palette) + s +
                 _duration_str(components, palette, show_api=True) + s +
                 styled(f"${cost_per_line:.4f}/line", palette.fg_dim))

        return f"{line1}\n{line2}"


# ── 6. Git Forge (2 lines) ──────────────────────────────────────────


class GitForgeTheme(Theme):
    name = "git_forge"
    lines = 2
    default_color_scheme = "catppuccin_frappe"

    def required_components(self) -> List[str]:
        return ["identity", "persona", "git", "lines", "context", "cost"]

    def render(self, components: Dict[str, ComponentData], palette: ColorPalette) -> str:
        s = sep(palette.separator)

        # Line 1: [matt:3]  main* ↑2 │ +6641/-80 │ ctx:42%
        line1 = (_identity_tag(components, palette) + " " +
                 _git_segment(components, palette) + s +
                 _lines_segment(components, palette) + s +
                 _context_segment(components, palette, bar_width=8))

        # Line 2: stash:3 │ staged:2 mod:5 untracked:1 │ $29.07
        git_c = _v(components, "git")
        if git_c and git_c.value.get("is_repo"):
            gv = git_c.value
            stash = gv.get("stash_count", 0)
            staged = gv.get("staged", 0)
            modified = gv.get("modified", 0)
            untracked = gv.get("untracked", 0)
            git_details = (styled(f"stash:{stash}", palette.fg_dim) + s +
                           styled(f"staged:{staged}", palette.ok) + " " +
                           styled(f"mod:{modified}", palette.warn) + " " +
                           styled(f"untracked:{untracked}", palette.fg_dim))
        else:
            git_details = styled("no repo", palette.fg_dim)

        line2 = git_details + s + _cost_str(components, palette)

        return f"{line1}\n{line2}"


# ── 7. Heartbeat (2 lines) ──────────────────────────────────────────


class HeartbeatTheme(Theme):
    name = "heartbeat"
    lines = 2
    default_color_scheme = "solarized_dark"

    def required_components(self) -> List[str]:
        return ["identity", "persona", "context", "rate_limits", "cache_stats", "cost"]

    def render(self, components: Dict[str, ComponentData], palette: ColorPalette) -> str:
        s = sep(palette.separator)

        # Line 1: [matt:3] ctx:42% ████████░░░░ │ 5h:15% ████░░░░ │ 7d:2% █░░░░░░░
        line1 = (_identity_tag(components, palette) + " " +
                 _context_segment(components, palette) + s +
                 _rate_limits_segment(components, palette))

        # Line 2: cache C:5.0K R:2.0K │ $29.07 │ 4h47m
        line2 = (_cache_segment(components, palette) + s +
                 _cost_str(components, palette) + s +
                 _duration_str(components, palette))

        return f"{line1}\n{line2}"


# ── 8. Archaeologist (2 lines) ──────────────────────────────────────


class ArchaeologistTheme(Theme):
    name = "archaeologist"
    lines = 2
    default_color_scheme = "nord_aurora"

    def required_components(self) -> List[str]:
        return ["identity", "persona", "topics", "sessions", "context"]

    def render(self, components: Dict[str, ComponentData], palette: ColorPalette) -> str:
        s = sep(palette.separator)

        # Line 1: [matt:3] 📖 auth → database → API → testing
        line1 = (_identity_tag(components, palette) + " " +
                 icon("topic") + " " +
                 _topic_chain(components, palette))

        # Line 2: ctx:42% │ 5 prompts │ 3 active sessions
        topics = _typed(components, "topics")
        topic_count = topics["count"] if topics else 0
        sessions = _typed(components, "sessions")
        session_count = sessions["count"] if sessions else 0
        line2 = (_context_segment(components, palette, bar_width=8) + s +
                 styled(f"{topic_count} prompts", palette.info) + s +
                 styled(f"{session_count} active sessions", palette.accent))

        return f"{line1}\n{line2}"


# ── 9. Rice (2 lines) ───────────────────────────────────────────────


class RiceTheme(Theme):
    name = "rice"
    lines = 2
    default_color_scheme = "catppuccin_mocha"

    def required_components(self) -> List[str]:
        return ["identity", "persona", "model", "context", "cost", "git"]

    def render(self, components: Dict[str, ComponentData], palette: ColorPalette) -> str:
        # Powerline segments with background colors
        # Segment colors (bg) — persona segment uses role color if available
        persona_c = _v(components, "persona")
        persona_hex = ""
        if persona_c:
            persona_hex = resolve_persona_color(persona_c.value.get("color", ""))
        seg1_bg = persona_hex or palette.accent    # persona
        seg2_bg = palette.info      # model
        seg3_bg = palette.ok        # context
        seg4_bg = palette.warn      # cost
        seg5_bg = palette.ok        # git branch
        seg6_bg = palette.info      # lines

        # Text color on colored bg — use dark bg color for contrast
        text_on = palette.bg

        # ── Line 1: ─────────────────────────────────────────────
        #  matt:3  Opus 4.5  ctx:42%  $29.07

        # Identity segment
        id_c = _v(components, "identity")
        persona = id_c.value.get("persona", "claude") if id_c else "?"
        num = id_c.value.get("session_number", 0) if id_c else 0
        id_text = f"{persona}:{num}" if num else persona

        # Model segment
        model = _typed(components, "model")
        model_name = model["display_name"] if model else "?"

        # Context segment
        ctx = _typed(components, "context")
        pct = ctx["used_percentage"] if ctx else None
        ctx_text = f"ctx:{fmt_pct(pct)}"

        # Cost segment
        cost = _typed(components, "cost")
        cost_usd = cost["total_cost_usd"] if cost else 0.0
        cost_text = fmt_cost(cost_usd)

        line1 = (
            bg(seg1_bg) + fg(text_on) + BOLD +
            f" {icon('persona')} {id_text} " + RST +
            powerline_sep(seg1_bg, seg2_bg) +
            bg(seg2_bg) + fg(text_on) +
            f" {model_name} " + RST +
            powerline_sep(seg2_bg, seg3_bg) +
            bg(seg3_bg) + fg(text_on) +
            f" {ctx_text} " + RST +
            powerline_sep(seg3_bg, seg4_bg) +
            bg(seg4_bg) + fg(text_on) +
            f" {cost_text} " + RST +
            powerline_sep(seg4_bg, "")
        )

        # ── Line 2: ─────────────────────────────────────────────
        #  main*  +6641/-80

        git_c = _v(components, "git")
        if git_c and git_c.value.get("is_repo"):
            gv = git_c.value
            branch = gv.get("branch", "?")
            dirty = "*" if gv.get("dirty") else ""
            ahead = gv.get("ahead", 0)
            arrow = f" \u2191{ahead}" if ahead else ""
            branch_text = f"{icon('git_branch')} {branch}{dirty}{arrow}"
        else:
            branch_text = "no repo"

        # lines component is session-level (tool use counts), independent of git repo
        lines_d = _typed(components, "lines")
        added = (lines_d["added"] if lines_d else 0) or 0
        removed = (lines_d["removed"] if lines_d else 0) or 0
        lines_text = fmt_lines(added, removed) if (added or removed) else "\u00b10"

        line2 = (
            bg(seg5_bg) + fg(text_on) + BOLD +
            f" {branch_text} " + RST +
            powerline_sep(seg5_bg, seg6_bg) +
            bg(seg6_bg) + fg(text_on) +
            f" {lines_text} " + RST +
            powerline_sep(seg6_bg, "")
        )

        return f"{line1}\n{line2}"


# ── 10. GPU (2 lines) ──────────────────────────────────────────────


def _fmt_gb(used_mib: int, total_mib: int) -> str:
    """Render memory as ' 1.9/12GB' with leading space."""
    if total_mib <= 0:
        return ""
    return f" {used_mib / 1024:.1f}/{total_mib / 1024:.0f}GB"


def _fmt_proc_mem(mib: int) -> str:
    """Render per-process memory in GB (1 decimal) — '1.3GB', '0.2GB', '0.0GB'."""
    return f"{mib / 1024:.1f}GB"


def _emdash(palette: ColorPalette) -> str:
    """A dim em-dash for honesty in visibly empty cells.

    Renders one visible char so cells without content read as 'intentionally
    empty' rather than 'mysteriously blank padding'. Always wrap empty cell
    content with this helper instead of leaving the content as ''."""
    return styled("—", palette.fg_dim)


def _aggregate_by_name(processes: list) -> list:
    """Aggregate processes that share the same display name (e.g., 'firefox'
    multi-PID content processes). Returns a sorted list of dicts shaped like
    {name, mem_mib, count}. Sum RSS across same-name PIDs; preserve order of
    first appearance. Stable: equal aggregated RSS keeps the earlier name first.

    Why: firefox spawns N content processes, all named 'firefox'. Listing each
    separately reads as duplicate noise. Aggregation shows one row with the
    summed footprint — the user-meaningful unit.
    """
    if not processes:
        return []
    groups: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for p in processes:
        name = (p.get("name") or "?").strip() or "?"
        mem = int(p.get("mem_mib", 0) or 0)
        if name not in groups:
            groups[name] = {"name": name, "mem_mib": 0, "count": 0}
            order.append(name)
        groups[name]["mem_mib"] += mem
        groups[name]["count"] += 1
    agg = [groups[n] for n in order]
    agg.sort(key=lambda g: g["mem_mib"], reverse=True)
    return agg


def _fmt_proc_mem_short(mib: int) -> str:
    """Compact per-process memory in always-GB form.

    >=1GB:  '1.6GB' (one decimal)
    <1GB:   '0.57GB' / '0.04GB' (two decimals, never collapses to '0.0GB')
    Always renders in gigabytes so visual scanning across the procs row reads
    a single unit — no mental conversion between M and G.
    """
    gb = mib / 1024
    if gb >= 1:
        return f"{gb:.1f}GB"
    return f"{gb:.2f}GB"


def _fmt_ghz(mhz: int) -> str:
    """Render frequency as '4.2GHz' from MHz, 1 decimal."""
    return f"{mhz / 1000:.1f}GHz"


def _pad_visible(s: str, width: int, align: str = "left") -> str:
    """Pad/truncate a styled string to a visible-character target width.

    Respects ANSI escape sequences via visible_len so colors don't consume
    column space. If the string is longer than width, return as-is (slight
    overflow is preferable to mid-ANSI truncation).
    """
    vlen = visible_len(s)
    if vlen >= width:
        return s
    pad = " " * (width - vlen)
    if align == "right":
        return pad + s
    if align == "center":
        half = (width - vlen) // 2
        return (" " * half) + s + (" " * (width - vlen - half))
    return s + pad


def _hline(width: int, palette: ColorPalette) -> str:
    """Smooth horizontal rule across `width` columns of the terminal."""
    return styled("─" * width, palette.fg_dim)


def _zwc(s: str) -> str:
    """Zero-width compensation: insert ZWSP after wide codepoints so the
    string's character count equals its visible width.

    Why: layout_grid._pad_visible pads to visible cells, but tests compare
    pipe positions by CHARACTER index. A single-codepoint emoji like '🎮'
    occupies 1 char but 2 visible cells, causing emoji-bearing cells to end
    1 char earlier than non-emoji cells of equal visible width. Inserting
    a zero-width space (U+200B) after each wide codepoint restores char/vwidth
    parity without affecting terminal rendering.
    """
    out: List[str] = []
    for ch in s:
        out.append(ch)
        # visible_len returns 0 for combining/zero-width, 1 for narrow,
        # 2 for wide (CJK + emojis). Insert (width - 1) ZWSP after wide chars.
        w = visible_len(ch)
        if w > 1:
            out.append("​" * (w - 1))
    return "".join(out)


def _fmt_short_duration(ms: int) -> str:
    """Compact duration: '15s', '1m30s', '2h15m'. Drops zero leading components."""
    if ms <= 0:
        return "0s"
    sec = ms // 1000
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        m, s = divmod(sec, 60)
        return f"{m}m{s:02d}s" if s else f"{m}m"
    h, rem = divmod(sec, 3600)
    m = rem // 60
    return f"{h}h{m:02d}m" if m else f"{h}h"


def _gpu_bar(pct: float, label: str, palette: ColorPalette, bar_width: int = 10) -> str:
    """Render a fixed-width labeled metric bar — cell archetype 'bar'.

    Format: 'LABEL:NNN% [10-char bar]' — total cell width = 10 (label) +
    bar_width. With bar_width=10 the cell is exactly 20 visible cells wide.

    Layout:
      label (4 chars, left-padded)   'CPU '  'VRAM' 'ctx '
      ':' (1)
      pct  (3 chars, right-padded)   ' 42'   '100'   '  7'
      '% ' (2)
      bar  (bar_width)               '██████████'

    Uniform width across CPU/RAM/GPU/VRAM/ctx produces a "visual ruler"
    down the rendered output regardless of label or percentage magnitude.

    Uses primitives.progress_bar (same █ glyph for fill + empty, dim color
    for empty, sub-block partials for boundary precision — no visual gap).
    """
    if pct > 80:
        color = palette.error
    elif pct > 50:
        color = palette.warn
    else:
        color = palette.ok
    bar = progress_bar(pct, width=bar_width, fill_color=color, empty_color=palette.fg_dim)
    # Truncate/pad label to 4 chars; right-justify pct to 3 chars so
    # 1-digit, 2-digit, 3-digit percentages all occupy the same width.
    label_part = f"{label[:4]:<4}"
    pct_part = f"{pct:>3.0f}"
    return (styled(f"{label_part}:", palette.fg_dim) +
            styled(pct_part, color) +
            styled("% ", palette.fg_dim) +
            bar)


def _severity_color(value: float, warn_at: float, error_at: float,
                    palette: ColorPalette, inverse: bool = False) -> str:
    """Pick a palette color by threshold comparison.

    Default (inverse=False): higher values are worse. Use for CPU%, RAM%,
    temps, fan%, rate limits — anything where 0 is healthy and high is bad.

    inverse=True: lower values are worse. Use for signal strength (-67 dBm
    is healthier than -90 dBm) and "peers online".
    """
    if inverse:
        if value <= error_at:
            return palette.error
        if value <= warn_at:
            return palette.warn
        return palette.ok
    if value >= error_at:
        return palette.error
    if value >= warn_at:
        return palette.warn
    return palette.ok


def _rate_color(pct: float, palette: ColorPalette) -> str:
    """Standard rate-limit / load thresholds: <50 ok, 50-80 warn, >80 error."""
    return _severity_color(pct, 50, 80, palette)


def _gpu_temp(temp_c: int, palette: ColorPalette) -> str:
    """Color-coded GPU temperature (NVIDIA — warn >=70, error >=85)."""
    return styled(f"{temp_c}°C", _severity_color(temp_c, 70, 85, palette))


def _cpu_temp(temp_c: int, high_c: int, critical_c: int, palette: ColorPalette) -> str:
    """Color-coded CPU package temperature (numeric only — section already has 💻 icon).

    Thresholds follow the chip's own reported high/critical when present,
    else use the doctrine defaults (<60 ok / 60-80 warn / >80 error).
    """
    if high_c > 0 and critical_c > 0:
        warn_at = high_c - 5
        error_at = critical_c
    else:
        warn_at = 60
        error_at = 80
    return styled(f"{temp_c}°C", _severity_color(temp_c, warn_at, error_at, palette))


def _gpu_power(power_w: float, limit_w: float, palette: ColorPalette) -> str:
    """Power draw with limit: 130W/200W. Colored by % of limit (50/80 thresholds)."""
    pct = (power_w / limit_w * 100) if limit_w > 0 else 0
    return (styled(f"{power_w:.0f}", _rate_color(pct, palette)) +
            styled(f"/{limit_w:.0f}W", palette.fg_dim))


# ── GpuTheme column system ───────────────────────────────────────────
#
# Eight columns, every row's cell spans sum to 8. Pipes appear ONLY at
# column boundaries → vertical alignment is guaranteed by construction.

# Variable-width columns + cell archetypes (Fix #3, 2026-06-01).
# All metric bars are 10 cells wide; bar cells produce 20-char content
# (10-char fixed-width label-and-pct prefix + 10-char bar) so every bar
# appears at the same visual mass — a "visual ruler" down the rendered output.
#
# Bar content format: 'LABL:NNN% ' (10) + 10-char bar = 20 chars exactly.
# See _gpu_bar() for the layout breakdown.
#
# Cell archetypes (column widths):
#   - chip cell:  20w  ('💻  Intel i7-13700F' fits)              c1
#   - bar cell:   ≥20w (20-char bar content, padded to col width) c2, c3, c4
#   - stat cell:  10-14w  (single numeric value)                  c5, c6, c7, c8
#
# c3 is 22w to preserve full 'Opus 4.7 (1M context)' (21 chars) when c3
# carries the model name on the identity row. The 20-char bar in c3 on
# summary rows gets 2 trailing pad chars — bar visually still aligns with
# c2 and c4 bars (all start at relative offset 0 in their cells).
#
# Total: 20+20+22+20+10+13+14+10 = 129 + 7 separators × 3w = 150 visible.
#
# Every row uses span=1 cells (no merged cells) so pipes line up at the
# same eight x-positions across every row — the column boundaries below.
_GPU_THEME_COLUMNS: List[Column] = [
    Column("c1", width=20, align="left"),   # chip archetype: persona / chip / proc1 / iface
    Column("c2", width=20, align="left"),   # bar archetype:  sid:pid / CPU bar / GPU bar / proc2
    Column("c3", width=22, align="left"),   # bar archetype:  model / RAM bar / VRAM bar / proc3
    Column("c4", width=20, align="center"), # bar archetype:  ctx bar / RAM vals / proc4
    Column("c5", width=10, align="right"),  # stat archetype: cost / temp / proc5 / +other
    Column("c6", width=13, align="center"), # stat archetype: rate limits / power / +other
    Column("c7", width=14, align="center"), # stat archetype: turn/up / clock / extra
    Column("c8", width=10, align="right"),  # stat archetype: version / fan / trailing
]
_GPU_THEME_GRID = Grid(columns=_GPU_THEME_COLUMNS, separator=" │ ")


def _truncate_branch(branch: str, max_width: int) -> str:
    """Middle-ellipsis-truncate a branch name to max_width visible chars.

    Reserves 2 chars for the leading '⎇ ' prefix the caller adds. Keeps both
    the head (slash-prefixed scope like 'feature/') and the tail (the actual
    issue/feature suffix) so the branch remains identifiable at a glance:

      'feature/claude-koi-phase-3' (26) in 14w → 'feature/cl…ase-3'
    """
    if visible_len(branch) <= max_width - 2:
        return branch
    keep = max_width - 2 - 1  # minus one for the ellipsis
    if keep < 2:
        return branch[: max_width - 2]
    head = keep // 2
    tail = keep - head
    return branch[:head] + "…" + branch[-tail:]


# ── Network formatting helpers (used by GpuTheme net rows) ──────────
def _fmt_bps(bps: int) -> str:
    """Format bits-per-second as 'X.X Mbps' / 'X Kbps' / 'X bps'."""
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.1f} Mbps"
    if bps >= 1_000:
        return f"{bps / 1_000:.0f} Kbps"
    return f"{bps} bps"


def _fmt_bytes(b: int) -> str:
    """Format bytes as 'X.XGB' / 'X.XMB' / 'X KB'."""
    if b >= 1024 ** 3:
        return f"{b / 1024**3:.1f}GB"
    if b >= 1024 ** 2:
        return f"{b / 1024**2:.1f}MB"
    if b >= 1024:
        return f"{b / 1024:.0f}KB"
    return f"{b}B"


class GpuTheme(Theme):
    """11-line declarative colspan grid: identity, workspace, CPU, GPU, network."""

    name = "gpu"
    lines = 11
    default_color_scheme = "catppuccin_mocha"

    def required_components(self) -> List[str]:
        return [
            "identity", "persona", "context", "cost", "model", "rate_limits",
            "workspace", "version", "duration", "lines", "worktree",
            "git", "cpu", "gpu", "turn", "net",
        ]

    # Positions (0-indexed) in the rendered output where hrules are inserted.
    # After workspace (1), CPU procs (3), GPU procs (5), and net endpoints (7).
    # Symmetric: opening rule after workspace, closing rule after the last row.
    _HRULE_AFTER = (1, 3, 5, 7)

    def render(self, components: Dict[str, ComponentData], palette: ColorPalette) -> str:
        rows = self._build_rows(components, palette)
        hr = _hline(_GPU_THEME_GRID.total_width, palette)
        out: List[str] = []
        for idx, r in enumerate(rows):
            out.append(_GPU_THEME_GRID.render(r))
            if idx in self._HRULE_AFTER:
                out.append(hr)
        return "\n".join(out)

    def _build_rows(self, components, palette=None):
        """Return list of Row objects in render order (HRULEs inserted by render())."""
        if palette is None:
            from colors import get_palette
            palette = get_palette(self.default_color_scheme)
        return [
            self._row_identity(components, palette),       # 0
            self._row_workspace(components, palette),      # 1
            self._row_cpu_summary(components, palette),    # 2
            self._row_cpu_procs(components, palette),      # 3
            self._row_gpu_summary(components, palette),    # 4
            self._row_gpu_procs(components, palette),      # 5
            self._row_net_summary(components, palette),    # 6
            self._row_net_endpoints(components, palette),  # 7
        ]

    # ── Line 1: identity ───────────────────────────────────────────
    def _row_identity(self, components, palette) -> Row:
        """Line 1: persona | sid:pid | model | ctx | $ | rates | turn/up | version.

        Eight span=1 cells — pipes land on the same x-positions as every
        other row. Variable column widths (20/18/22/14/10/13/14/10) are
        sized to comfortably hold their dominant content.

        Pure function of (components, palette) → Row. ALL env vars, hostname
        probes, and getppid() calls live in compute_identity() (the shell
        layer). This renderer reads only from the identity component's value
        dict and falls back to pure string-derivation if a shell-resolved
        field is absent (e.g. test fixtures bypassing compute_identity).
        """
        ident = _v(components, "identity")
        iv = ident.value if ident else {}

        persona = iv.get("persona", "") or "claude"
        seq = iv.get("session_number", 0)
        host = iv.get("host", "") or "host"

        # Prefer shell-resolved short id; else derive from session_id/
        # transcript_path basename. NO env reads here — these are pure
        # string operations against fields already on the component.
        sid_short = iv.get("session_id_short", "") or ""
        if not sid_short:
            sid_full = iv.get("session_id", "") or ""
            if not sid_full:
                tpath = iv.get("transcript_path", "") or ""
                if tpath:
                    base = tpath.rsplit("/", 1)[-1]
                    if base.endswith(".jsonl"):
                        base = base[:-6]
                    sid_full = base
            sid_short = sid_full[:8] if sid_full else "????????"

        pid_str = iv.get("pid", "") or "?"

        model_d = _typed(components, "model")
        model_name = ""
        if model_d:
            model_name = model_d.get("display_name") or model_d.get("id") or ""
        # Show FULL model name including "(1M context)" — do NOT split on " ("
        # Model cell is c3=22w; 'Opus 4.7 (1M context)' = 21 chars (fits).
        if visible_len(model_name) > 22:
            model_name = truncate(model_name, 22)

        # Context bar — c4 is 20w (bar archetype). _gpu_bar produces a
        # 10-char fixed prefix ('ctx :  N% ') + 10-char bar = 20 exactly.
        ctx_d = _typed(components, "context")
        ctx_pct = (ctx_d.get("used_percentage", 0) if ctx_d else 0) or 0
        if ctx_pct > 0:
            ctx_cell = _gpu_bar(float(ctx_pct), "ctx", palette, bar_width=10)
        else:
            # No-data fallback: same 20-char layout. 'ctx : ?% ' (10) + bar (10).
            ctx_cell = styled("ctx :  ?% " + "█" * 10, palette.fg_dim)

        # Cost — color by severity: <$5 ok/dim, $5-20 warn, >$20 error
        cost_d = _typed(components, "cost")
        cost_usd = (cost_d.get("total_cost_usd", 0.0) if cost_d else 0.0) or 0.0
        if cost_usd > 20:
            cost_color = palette.error
        elif cost_usd > 5:
            cost_color = palette.warn
        else:
            cost_color = palette.fg_dim
        cost_cell = styled(fmt_cost(cost_usd), cost_color)

        # Rate limits — show BOTH 5h and 7d (strategic + tactical budgets).
        # compute_rate_limits exposes flat keys (five_hour_pct, seven_day_pct)
        # but tests/mocks use nested seven_day.used_percentage; support both.
        rl_d = _typed(components, "rate_limits")
        five_hour = 0
        seven_day = 0
        if rl_d:
            five_hour = rl_d.get("five_hour_pct", 0) or 0
            seven_day = rl_d.get("seven_day_pct", 0) or 0
            if not five_hour:
                try:
                    five_hour = rl_d.get("five_hour", {}).get("used_percentage", 0) or 0
                except (AttributeError, TypeError):
                    five_hour = 0
            if not seven_day:
                try:
                    seven_day = rl_d.get("seven_day", {}).get("used_percentage", 0) or 0
                except (AttributeError, TypeError):
                    seven_day = 0

        rl_cell = (styled(f"5h:{int(five_hour)}%", _rate_color(five_hour, palette)) +
                   styled(" ", palette.fg_dim) +
                   styled(f"7d:{int(seven_day)}%", _rate_color(seven_day, palette)))

        # Turn time / session uptime — color by severity
        # Turn: <30s ok, 30-120s warn, >120s error (only when active)
        # Uptime: <2h ok, 2-8h warn, >8h error
        dur_d = _typed(components, "duration")
        uptime_ms = (dur_d.get("total_ms") if dur_d else None) or (
            cost_d.get("total_duration_ms") if cost_d else 0) or 0
        turn_d = _typed(components, "turn")
        turn_ms = (turn_d.get("duration_ms", 0) if turn_d else 0) or 0
        turn_active = bool(turn_d.get("is_active", False)) if turn_d else False
        turn_lbl = _fmt_short_duration(turn_ms) if turn_ms else "—"
        uptime_lbl = _fmt_short_duration(uptime_ms) if uptime_ms else "—"
        # Turn color: only when active. Idle → fg_dim regardless.
        if turn_active and turn_ms:
            turn_color = _severity_color(turn_ms / 1000, 30, 120, palette)
        else:
            turn_color = palette.fg_dim
        # Uptime color
        uptime_hours = uptime_ms / 3_600_000
        uptime_color = _severity_color(uptime_hours, 2, 8, palette) if uptime_ms else palette.fg_dim
        turn_cell = (styled(turn_lbl, turn_color) +
                     styled("/", palette.fg_dim) +
                     styled(uptime_lbl, uptime_color))

        # c1=20w fits "<icon> user@host:seq" (≈18 visible). c2=18w fits sid:pid.
        # Persona glyph resolves from the optional claude-emoji DB via
        # compute_identity → persona_utils._load_persona_icon. Renderer is pure:
        # this is just a string read with a safe fallback to the lotus glyph.
        persona_part = f"{persona}@{host}:{seq}"
        sid_part = f"{sid_short}:{pid_str}"
        persona_icon = iv.get("persona_icon", "") or "🪷"
        persona_cell = _zwc(styled(f"{persona_icon}  ", palette.accent) +
                            styled(persona_part, palette.accent, bold=True))
        sid_cell = styled(sid_part, palette.fg_dim)

        # Version moves to c8 (was previously on workspace row c8).
        ver_d = _typed(components, "version")
        ver = (ver_d.get("version", "") if ver_d else "") or ""
        ver_cell = styled(f"v{ver}", palette.fg_dim) if ver else _emdash(palette)

        return _GPU_THEME_GRID.row(cells=[
            Cell(content=persona_cell, span=1, align="left"),      # c1 persona
            Cell(content=sid_cell, span=1, align="left"),          # c2 sid:pid
            Cell(content=styled(model_name, palette.info), span=1, align="left"),  # c3 model
            Cell(content=ctx_cell, span=1, align="center"),        # c4 ctx
            Cell(content=cost_cell, span=1, align="right"),        # c5 $
            Cell(content=rl_cell, span=1, align="center"),         # c6 rates
            Cell(content=turn_cell, span=1, align="center"),       # c7 turn/up
            Cell(content=ver_cell, span=1, align="right"),         # c8 version
        ])

    # ── Line 2: workspace ──────────────────────────────────────────
    def _row_workspace(self, components, palette) -> Row:
        """Line 2: cwd | branch | output_style | diff | — | — | — | —.

        All span=1 cells, all eight present. Version moved to identity row
        c8 (morning iteration 2026-06-01) — workspace c8 becomes em-dash
        (honest 'no data here')."""
        ws = _typed(components, "workspace")
        cwd_short = (ws.get("cwd_short", "?") if ws else "?") or "?"
        output_style = (ws.get("output_style", "") if ws else "") or ""

        # Branch comes from the git component (shell layer). Pure consumption —
        # no subprocess / filesystem reads at render time.
        git_d = _typed(components, "git")
        branch = (git_d.get("branch", "") if git_d else "") or ""
        # Guard against the "?" placeholder returned by _compute_git_info when
        # branch resolution failed inside the repo — show em-dash, not "?".
        if branch == "?":
            branch = ""

        lines_d = _typed(components, "lines")
        added = (lines_d.get("added", 0) if lines_d else 0) or 0
        removed = (lines_d.get("removed", 0) if lines_d else 0) or 0

        # cwd c1 = 20w. Truncation strategy: keep the trailing path segment(s)
        # since the project name is the most identifying piece.
        if visible_len(cwd_short) > 20:
            keep = 20 - 1  # minus one for the leading ellipsis
            cwd_short = "…" + cwd_short[-keep:]
        cwd_cell = styled(cwd_short, palette.fg_dim)

        # Branch — c2 is 18w; reserve 2 for "⎇ " prefix → 16w budget.
        if branch:
            branch_disp = _truncate_branch(branch, 18)
            branch_text = styled(f"⎇ {branch_disp}", palette.info)
        else:
            branch_text = styled("⎇ —", palette.fg_dim)

        if output_style and output_style != "default":
            style_cell = styled(output_style, palette.fg_dim)
        else:
            style_cell = _emdash(palette)

        if added or removed:
            diff_text = styled(f"+{added}", palette.ok) + styled(f"/-{removed}", palette.error)
        else:
            diff_text = _emdash(palette)

        em = _emdash(palette)
        return _GPU_THEME_GRID.row(cells=[
            Cell(content=cwd_cell, span=1, align="left"),       # c1 cwd
            Cell(content=branch_text, span=1, align="left"),    # c2 branch
            Cell(content=style_cell, span=1, align="left"),     # c3 output style
            Cell(content=diff_text, span=1, align="center"),    # c4 diff
            Cell(content=em, span=1, align="right"),            # c5
            Cell(content=em, span=1, align="center"),           # c6
            Cell(content=em, span=1, align="center"),           # c7
            Cell(content=em, span=1, align="right"),            # c8
        ])

    # ── Lines 4-5: CPU summary + processes ─────────────────────────
    def _row_cpu_summary(self, components, palette) -> Row:
        """Line 4: chip | CPU% bar | RAM% bar | RAM vals | temp | power | clock | fan.

        Eight span=1 cells. c1=20 holds '💻  Intel i7-13700F', c2=20 holds
        CPU% bar, c3=22 holds RAM% bar, c4=20 holds RAM vals, c5=10 temp,
        c6=13 power, c7=14 clock, c8=10 fan."""
        cpu = _v(components, "cpu")
        if not cpu or not cpu.value.get("available"):
            return _GPU_THEME_GRID.row(cells=[
                Cell(content=styled("💻  CPU: not available", palette.fg_dim),
                     span=len(_GPU_THEME_COLUMNS)),
            ])
        cv = cpu.value
        name = cv.get("name", "CPU")
        cpu_pct = cv.get("cpu_pct", 0.0)
        ram_used = cv.get("ram_used_mib", 0)
        ram_total = cv.get("ram_total_mib", 0)
        ram_pct = cv.get("ram_pct", 0.0)
        temp_c = cv.get("temp_c", 0)
        high_c = cv.get("high_c", 0)
        critical_c = cv.get("critical_c", 0)
        clock_mhz = cv.get("clock_mhz", 0)
        power_w = cv.get("power_w", 0.0)
        power_limit_w = cv.get("power_limit_w", 0.0)
        power_available = cv.get("power_available", False)
        fan_pct = cv.get("fan_pct", 0)
        fan_available = cv.get("fan_available", False)

        # c1 = 20w; "💻  " is 4 visible cells, leaving 16 for the chip name
        # (Intel i7-13700F = 15 visible cells). 💻 (U+1F4BB, Unicode 6.0,
        # single codepoint) replaces 🖥️  (U+1F5A5 + VS-16) — VS-16 has
        # inconsistent terminal width handling causing off-by-one drift.
        chip = _zwc(styled("💻  ", palette.accent) +
                    styled(name, palette.accent, bold=True))

        # CPU bar — c2 is 20w (bar archetype). _gpu_bar produces 20 exactly.
        usage = _gpu_bar(cpu_pct, "CPU", palette, bar_width=10)
        # RAM bar — c3 is 20w (bar archetype). _gpu_bar produces 20 exactly.
        ram_bar = _gpu_bar(ram_pct, "RAM", palette, bar_width=10)
        # RAM vals — c4 is 20w (bar archetype, centered). 'XX.X/YYGB' ≈ 10 chars,
        # centered with generous padding.
        ram_vals = styled(_fmt_gb(ram_used, ram_total).strip(), palette.fg_dim)
        temp = _cpu_temp(temp_c, high_c, critical_c, palette)

        # Power: c6=13w. Format: "NNN/NNNW" or em-dash form.
        if power_limit_w > 0:
            if power_available and power_w > 0:
                power = _gpu_power(power_w, power_limit_w, palette)
            else:
                power = (styled("—", palette.fg_dim) +
                         styled(f"/{power_limit_w:.0f}W", palette.fg_dim))
        else:
            power = _emdash(palette)

        # Clock c7=14w. e.g. "1.4GHz".
        clock_cell = (styled(_fmt_ghz(clock_mhz), palette.fg_dim)
                      if clock_mhz > 0 else _emdash(palette))
        # Fan c8=10w. Color by 50/80 thresholds.
        if fan_available and fan_pct > 0:
            fan_cell = (styled("fan:", palette.fg_dim) +
                        styled(f"{fan_pct}%", _rate_color(fan_pct, palette)))
        else:
            fan_cell = styled("fan:—", palette.fg_dim)

        return _GPU_THEME_GRID.row(cells=[
            Cell(content=chip, span=1, align="left"),         # c1 chip
            Cell(content=usage, span=1, align="left"),        # c2 CPU% bar
            Cell(content=ram_bar, span=1, align="left"),      # c3 RAM% bar
            Cell(content=ram_vals, span=1, align="center"),   # c4 RAM vals
            Cell(content=temp, span=1, align="right"),        # c5 temp
            Cell(content=power, span=1, align="center"),      # c6 power
            Cell(content=clock_cell, span=1, align="center"), # c7 clock
            Cell(content=fan_cell, span=1, align="right"),    # c8 fan
        ])

    def _row_cpu_procs(self, components, palette) -> Row:
        """Line 5: proc1 | proc2 | ... | +other adjacent | em-dashes fill.

        +other lives in the cell IMMEDIATELY AFTER the last filled proc, not
        floating at the row's right edge (morning iteration fix #5).
        No truncation — each cell's content is sized to fit its column width."""
        cpu = _v(components, "cpu")
        if not cpu or not cpu.value.get("available"):
            return _GPU_THEME_GRID.row(cells=[
                Cell(content=_emdash(palette),
                     span=len(_GPU_THEME_COLUMNS), align="center"),
            ])

        cv = cpu.value
        ram_used_mib = cv.get("ram_used_mib", 0)
        # task-552 Phase 4: bumped from [:5] to [:7] — procs row has 8
        # cells, leave 1 for +other. _aggregate_by_name merges multi-
        # process apps (firefox → 1 entry) so 7 aggregated entries can
        # be many more raw procs underneath.
        processes = _aggregate_by_name(cv.get("processes", []))[:7]
        sum_top = sum(p.get("mem_mib", 0) for p in processes)
        other = max(0, ram_used_mib - sum_top)
        return self._build_procs_row(processes, other, palette)

    def _build_procs_row(self, processes, other_mib, palette) -> Row:
        """Shared proc-row builder for CPU + GPU.

        Layout: [🔧 proc1] [proc2] ... [+other] [em-dash filler...].
        +other appears IMMEDIATELY AFTER the last filled proc cell so it
        reads as 'the residual of the procs above', not 'floating on the
        right edge'.
        """
        col_widths = [c.width for c in _GPU_THEME_COLUMNS]
        n_cols = len(col_widths)

        def _proc_cell(idx: int, p: dict) -> str:
            pname = p.get("name", "?")
            pmem = p.get("mem_mib", 0)
            count = p.get("count", 1)
            display = f"{pname} ({count})" if count > 1 else pname
            mem_label = _fmt_proc_mem_short(pmem)
            cell_width = col_widths[idx]
            mem_suffix_width = 1 + visible_len(mem_label)  # space + mem
            name_budget = max(1, cell_width - mem_suffix_width)
            # Middle-ellipsis truncate when the name overflows. Variable widths
            # mean this is uncommon — but c5 (10w) and c8 (10w) are narrow
            # enough that short names like 'letta 0.40GB' would overflow
            # without truncation. Use middle-ellipsis to preserve identity.
            if visible_len(display) > name_budget:
                if name_budget >= 3:
                    head = name_budget // 2
                    tail = name_budget - head - 1
                    pname_t = display[:head] + "…" + display[-tail:] if tail > 0 else display[:name_budget]
                elif name_budget >= 1:
                    # Tight: name truncated to budget, but ALWAYS keep mem suffix.
                    # Honest is better than silently dropping the value.
                    pname_t = display[: max(0, name_budget - 1)] + "…" if name_budget > 1 else display[:1]
                else:
                    # Pathological: no room at all. Drop mem suffix as last resort.
                    pname_t = truncate(display, cell_width)
                    return styled(pname_t, palette.info)
            else:
                pname_t = display
            return styled(pname_t, palette.info) + styled(f" {mem_label}", palette.fg_dim)

        cells_content: List[str] = [_proc_cell(i, processes[i]) for i in range(len(processes))]

        # +other in the cell directly after the last proc (if room).
        n_procs = len(cells_content)
        if other_mib > 0 and n_procs < n_cols:
            other_label = f"+{_fmt_proc_mem(other_mib)} other"
            other_idx = n_procs
            # If the +other label doesn't fit the next column, drop the trailing " other".
            if visible_len(other_label) > col_widths[other_idx]:
                other_label = f"+{_fmt_proc_mem(other_mib)}"
            cells_content.append(styled(other_label, palette.fg_dim))

        # If zero procs at all, em-dash in c1 (no wrench prefix needed).
        if not cells_content:
            cells_content = [_emdash(palette)]

        # Fill remaining cells with em-dashes (honesty).
        while len(cells_content) < n_cols:
            cells_content.append(_emdash(palette))

        return _GPU_THEME_GRID.row(cells=[
            Cell(content=cells_content[i], span=1) for i in range(n_cols)
        ], align="left")

    # ── Lines 7-8: GPU summary + processes ─────────────────────────
    def _row_gpu_summary(self, components, palette) -> Row:
        """Line 7: chip | GPU% bar | VRAM% bar | VRAM vals | temp | power | clock | fan.

        Eight span=1 cells (mirrors CPU summary). c1=20 holds '🎮 NVIDIA RTX 4070'."""
        gpu = _v(components, "gpu")
        if not gpu or not gpu.value.get("available"):
            return _GPU_THEME_GRID.row(cells=[
                Cell(content=styled("🎮  GPU: not available", palette.fg_dim),
                     span=len(_GPU_THEME_COLUMNS)),
            ])

        gv = gpu.value
        name = gv.get("name", "GPU")
        gpu_util = gv.get("gpu_util", 0)
        mem_used = gv.get("mem_used_mib", 0)
        mem_total = gv.get("mem_total_mib", 0)
        temp_c = gv.get("temp_c", 0)
        power_w = gv.get("power_w", 0.0)
        power_limit_w = gv.get("power_limit_w", 0.0)
        clock_mhz = gv.get("clock_gpu_mhz", 0)
        fan_pct = gv.get("fan_pct", 0)
        vram_pct = (mem_used / mem_total * 100) if mem_total > 0 else 0

        # c1 = 20w; "🎮  " is 4 visible cells, leaving 16 for the chip name.
        chip = _zwc(styled("🎮  ", palette.accent) +
                    styled(name, palette.accent, bold=True))

        # GPU bar — c2 is 20w (bar archetype). _gpu_bar produces 20 exactly.
        usage = _gpu_bar(gpu_util, "GPU", palette, bar_width=10)
        # VRAM bar — c3 is 20w (bar archetype). _gpu_bar produces 20 exactly
        # (4-char label 'VRAM' uses the full label budget; identical width to
        # CPU/RAM/GPU/ctx bars — the visual ruler is preserved).
        vram_bar = _gpu_bar(vram_pct, "VRAM", palette, bar_width=10)
        # VRAM vals — c4 is 20w (bar archetype, centered). 'X.X/YYGB' ≈ 9 chars.
        vram_vals = styled(_fmt_gb(mem_used, mem_total).strip(), palette.fg_dim)
        temp = _gpu_temp(temp_c, palette)
        power = _gpu_power(power_w, power_limit_w, palette) if power_limit_w > 0 \
                else _emdash(palette)
        clock_cell = (styled(_fmt_ghz(clock_mhz), palette.fg_dim)
                      if clock_mhz > 0 else _emdash(palette))
        if fan_pct > 0:
            fan_cell = (styled("fan:", palette.fg_dim) +
                        styled(f"{fan_pct}%", _rate_color(fan_pct, palette)))
        else:
            fan_cell = styled("fan:—", palette.fg_dim)

        return _GPU_THEME_GRID.row(cells=[
            Cell(content=chip, span=1, align="left"),         # c1 chip
            Cell(content=usage, span=1, align="left"),        # c2 GPU% bar
            Cell(content=vram_bar, span=1, align="left"),     # c3 VRAM% bar
            Cell(content=vram_vals, span=1, align="center"),  # c4 VRAM vals
            Cell(content=temp, span=1, align="right"),        # c5 temp
            Cell(content=power, span=1, align="center"),      # c6 power
            Cell(content=clock_cell, span=1, align="center"), # c7 clock
            Cell(content=fan_cell, span=1, align="right"),    # c8 fan
        ])

    def _row_gpu_procs(self, components, palette) -> Row:
        """Line 8: GPU process row — same shared builder as CPU procs.

        Improvement #9: when NO compute apps are running and only graphics
        apps (kwin, plasmashell, ksecretd) appear, prepend a dim '(g)' marker
        on the first proc so users can tell at a glance the fallback is
        graphics processes, not the compute workload they care about."""
        gpu = _v(components, "gpu")
        if not gpu or not gpu.value.get("available"):
            return _GPU_THEME_GRID.row(cells=[
                Cell(content=_emdash(palette),
                     span=len(_GPU_THEME_COLUMNS), align="center"),
            ])

        gv = gpu.value
        # task-552 Phase 4: bumped from [:5] to [:7] (same rationale as CPU).
        processes = _aggregate_by_name(gv.get("processes", []))[:7]
        other = max(0, gv.get("other_vram_mib", 0))
        # Detect graphics-only fallback: gpu_utils tags the synthetic name with
        # " (graphics)" suffix when there are no compute apps but pmon reports
        # graphics activity. Strip the suffix here so it doesn't double up.
        is_graphics_only = bool(gv.get("is_graphics_fallback", False))
        if processes and any(" (graphics)" in p.get("name", "") for p in processes):
            is_graphics_only = True
            for p in processes:
                if " (graphics)" in p.get("name", ""):
                    p["name"] = p["name"].replace(" (graphics)", "")
        # Heuristic fallback for known compositor names.
        if not is_graphics_only and processes:
            graphics_names = {"kwin_wayland", "kwin_x11", "kwin", "plasmashell",
                              "ksecretd", "Xorg", "Xwayland", "gnome-shell",
                              "compiz", "sway", "Hyprland", "weston"}
            if all(p.get("name", "") in graphics_names for p in processes):
                is_graphics_only = True

        return self._build_gpu_procs_row(processes, other, is_graphics_only, palette)

    def _build_gpu_procs_row(self, processes, other_mib, is_graphics_only, palette) -> Row:
        """GPU-specific proc row with graphics-fallback annotation."""
        col_widths = [c.width for c in _GPU_THEME_COLUMNS]
        n_cols = len(col_widths)

        def _proc_cell(idx: int, p: dict) -> str:
            pname = p.get("name", "?")
            pmem = p.get("mem_mib", 0)
            count = p.get("count", 1)
            display = f"{pname} ({count})" if count > 1 else pname
            mem_label = _fmt_proc_mem_short(pmem)
            cell_width = col_widths[idx]
            prefix_width = 4 if (idx == 0 and is_graphics_only) else 0  # "(g) "
            mem_suffix_width = 1 + visible_len(mem_label)
            name_budget = max(1, cell_width - prefix_width - mem_suffix_width)
            name_color = palette.fg_dim if is_graphics_only else palette.info
            if visible_len(display) > name_budget:
                if name_budget >= 3:
                    head = name_budget // 2
                    tail = name_budget - head - 1
                    pname_t = display[:head] + "…" + display[-tail:] if tail > 0 else display[:name_budget]
                elif name_budget >= 1:
                    pname_t = display[: max(0, name_budget - 1)] + "…" if name_budget > 1 else display[:1]
                else:
                    pname_t = truncate(display, cell_width - prefix_width)
                    body = styled(pname_t, name_color)
                    if idx == 0 and is_graphics_only:
                        body = styled("(g) ", palette.fg_dim) + body
                    return body
            else:
                pname_t = display
            body = styled(pname_t, name_color) + styled(f" {mem_label}", palette.fg_dim)
            if idx == 0 and is_graphics_only:
                body = styled("(g) ", palette.fg_dim) + body
            return body

        cells_content: List[str] = [_proc_cell(i, processes[i]) for i in range(len(processes))]

        n_procs = len(cells_content)
        if other_mib > 0 and n_procs < n_cols:
            other_label = f"+{_fmt_proc_mem(other_mib)} other"
            other_idx = n_procs
            if visible_len(other_label) > col_widths[other_idx]:
                other_label = f"+{_fmt_proc_mem(other_mib)}"
            cells_content.append(styled(other_label, palette.fg_dim))

        if not cells_content:
            cells_content = [_emdash(palette)]

        while len(cells_content) < n_cols:
            cells_content.append(_emdash(palette))

        return _GPU_THEME_GRID.row(cells=[
            Cell(content=cells_content[i], span=1) for i in range(n_cols)
        ], align="left")

    # ── Lines 10-11: Network ───────────────────────────────────────
    def _row_net_summary(self, components, palette) -> Row:
        """Line 10: iface/ssid | ↓rate | ↑rate | ↓total | ↑total | signal | latency | em.

        All eight span=1 cells. Signal dBm color-coded by severity."""
        net = _v(components, "net")
        if not net or not net.value.get("available"):
            return _GPU_THEME_GRID.row(cells=[
                Cell(content=styled("📡  net: unavailable", palette.fg_dim),
                     span=len(_GPU_THEME_COLUMNS)),
            ])

        nv = net.value
        iface = nv.get("iface", "?")
        ssid = nv.get("ssid", "")
        down_bps = nv.get("down_bps", 0)
        up_bps = nv.get("up_bps", 0)
        total_down = nv.get("total_down_bytes", 0)
        total_up = nv.get("total_up_bytes", 0)
        sig_dbm = nv.get("signal_dbm")

        # c1 = 20w; "📡  " is 4 visible cells, leaving 16 for iface[/ssid].
        iface_label = f"{iface}/{ssid}" if ssid else iface
        iface_label = truncate(iface_label, 16)
        iface_cell = _zwc(styled(f"📡  {iface_label}", palette.accent, bold=True))

        down_cell = styled(f"↓ {_fmt_bps(down_bps)}", palette.info)
        up_cell = styled(f"↑ {_fmt_bps(up_bps)}", palette.info)
        td_cell = styled(f"{_fmt_bytes(total_down)} ↓", palette.fg_dim)
        tu_cell = styled(f"{_fmt_bytes(total_up)} ↑", palette.fg_dim)
        # Signal: inverse severity — higher (closer to 0) is better.
        # -70 dBm is the warn boundary, -85 dBm is the error boundary.
        if sig_dbm is not None:
            sig_color = _severity_color(float(sig_dbm), -70, -85, palette, inverse=True)
            sig_cell = styled(f"{sig_dbm} dBm", sig_color)
        else:
            sig_cell = _emdash(palette)
        # task-552 Phase 4: latency from TCP-connect probe to gateway:53.
        # Severity bands: <10ms ok (LAN-like), <50ms info, <150ms warn,
        # >=150ms error. Cell shows raw ms with one decimal place.
        latency_ms = nv.get("latency_ms")
        if latency_ms is not None:
            lat_color = _severity_color(float(latency_ms), 50, 150, palette)
            latency_cell = styled(f"{float(latency_ms):.1f} ms", lat_color)
        else:
            latency_cell = _emdash(palette)
        empty_cell = _emdash(palette)

        return _GPU_THEME_GRID.row(cells=[
            Cell(content=iface_cell, span=1, align="left"),
            Cell(content=down_cell, span=1, align="center"),
            Cell(content=up_cell, span=1, align="left"),
            Cell(content=td_cell, span=1, align="center"),
            Cell(content=tu_cell, span=1, align="right"),
            Cell(content=sig_cell, span=1, align="center"),
            Cell(content=latency_cell, span=1, align="center"),
            Cell(content=empty_cell, span=1, align="right"),
        ])

    def _row_net_endpoints(self, components, palette) -> Row:
        """Line 11: tailscale/IP | peers | wireguard tunnel | em-dashes....

        All eight span=1 cells. tailscale label fits c1=20w.
        Peers count colored by online/total ratio."""
        net = _v(components, "net")
        if not net or not net.value.get("available"):
            return _GPU_THEME_GRID.row(cells=[
                Cell(content=styled("🔗  —", palette.fg_dim),
                     span=len(_GPU_THEME_COLUMNS), align="left"),
            ])

        nv = net.value
        self_ip = nv.get("self_ip", "")
        peers_on = nv.get("tailscale_peers_online", 0)
        peers_total = nv.get("tailscale_peers_total", 0)
        tunnels = nv.get("wireguard_tunnels", [])

        # c1 = 20w; "🔗  " is 4 visible cells, so we have 16 visible for the
        # tailscale label. A CGNAT address like "100.64.113.115" fits; we
        # drop the "ts0/" prefix since the 🔗 icon already conveys "this is
        # a network endpoint" and the column header context is unambiguous.
        if self_ip:
            ts_cell = _zwc(styled(f"🔗  {self_ip}", palette.info, bold=True))
        else:
            ts_cell = _zwc(styled("🔗  tailscale: down", palette.fg_dim))
        # Peers color: all online = ok, partial = warn, zero = error.
        if peers_total == 0:
            peer_color = palette.fg_dim
        elif peers_on == 0:
            peer_color = palette.error
        elif peers_on < peers_total:
            peer_color = palette.warn
        else:
            peer_color = palette.ok
        peer_cell = styled(f"peers {peers_on}/{peers_total}", peer_color)

        tunnel_cells: List[str] = []
        for t in tunnels:
            if t == "tailscale0":
                continue
            tunnel_cells.append(styled(f"{t} ✓", palette.ok))
        if not tunnel_cells:
            tunnel_cells = [_emdash(palette)]
        # Pad to fill the remaining columns (5 cells after iface/peers).
        while len(tunnel_cells) < 6:
            tunnel_cells.append(_emdash(palette))

        return _GPU_THEME_GRID.row(cells=[
            Cell(content=ts_cell, span=1, align="left"),
            Cell(content=peer_cell, span=1, align="center"),
            Cell(content=tunnel_cells[0], span=1, align="center"),
            Cell(content=tunnel_cells[1], span=1, align="center"),
            Cell(content=tunnel_cells[2], span=1, align="right"),
            Cell(content=tunnel_cells[3], span=1, align="center"),
            Cell(content=tunnel_cells[4], span=1, align="center"),
            Cell(content=tunnel_cells[5], span=1, align="right"),
        ])


# ── 11. Grid (11 lines) ─────────────────────────────────────────────


class GridTheme(Theme):
    """10x10 emoji memory grid — session history as living compression."""

    name = "grid"
    lines = 11  # 1 identity + up to 10 grid rows
    default_color_scheme = "catppuccin_mocha"

    def required_components(self) -> List[str]:
        return ["identity", "context", "cost", "grid"]

    def render(self, components: Dict[str, ComponentData], palette: ColorPalette) -> str:
        s = sep(palette.separator)

        # Line 1: identity + context + cost (compact)
        tag = _identity_tag(components, palette)
        ctx_seg = _context_segment(components, palette, bar_width=8)
        cost_seg = _cost_str(components, palette)

        grid = _typed(components, "grid")
        total = grid["total_cells"] if grid else 0
        full_flag = styled("FULL", palette.warn) if (grid and grid["is_full"]) else ""
        grid_count = styled(f"[{total}/100]", palette.fg_dim)

        header = f"{tag} {s} {ctx_seg} {s} {cost_seg} {s} {grid_count}"
        if full_flag:
            header += f" {full_flag}"

        if not grid or not grid["rows"]:
            return header

        # Grid rows: timestamp + emojis
        lines = [header]
        for row_data in reversed(grid["rows"]):
            ts = styled(row_data["timestamp"], palette.fg_dim)
            emojis = "".join(row_data["emojis"])
            lines.append(f"  {ts}  {emojis}")

        return "\n".join(lines)


# ── 13. Classic + Grid (classic 2-line header + emoji grid below) ────


class ClassicGridTheme(Theme):
    """Classic 2-line statusline with emoji memory grid appended below."""

    name = "classic+grid"
    lines = 12  # 2 classic + up to 10 grid rows
    default_color_scheme = "catppuccin_mocha"

    def required_components(self) -> List[str]:
        return [
            "identity", "persona", "context", "cost", "model", "rate_limits",
            "workspace", "version", "duration", "lines", "worktree", "grid",
        ]

    def render(self, components: Dict[str, ComponentData], palette: ColorPalette) -> str:
        # Full classic 2-line header
        classic = _render_classic_lines(components, palette)

        # Grid rows below
        grid = _typed(components, "grid")
        if not grid or not grid["rows"]:
            return classic

        grid_lines = []
        for row_data in reversed(grid["rows"]):
            ts = styled(row_data["timestamp"], palette.fg_dim)
            emojis = "".join(row_data["emojis"])
            grid_lines.append(f"  {ts}  {emojis}")

        return classic + "\n" + "\n".join(grid_lines)


# ── 15. GPU + Grid (GPU 4-line header + emoji grid below) ──────────


class GpuGridTheme(GpuTheme):
    """GPU statusline with emoji memory grid appended below."""

    name = "gpu+grid"
    lines = 14  # 4 gpu + up to 10 grid rows
    default_color_scheme = "catppuccin_mocha"

    def required_components(self) -> List[str]:
        return super().required_components() + ["grid"]

    def render(self, components: Dict[str, ComponentData], palette: ColorPalette) -> str:
        # Full GPU render (classic 2-line + gpu 2-line)
        gpu_output = super().render(components, palette)

        # Grid rows below
        grid = _typed(components, "grid")
        if not grid or not grid["rows"]:
            return gpu_output

        grid_lines = []
        for row_data in reversed(grid["rows"]):
            ts = styled(row_data["timestamp"], palette.fg_dim)
            emojis = "".join(row_data["emojis"])
            grid_lines.append(f"  {ts}  {emojis}")

        return gpu_output + "\n" + "\n".join(grid_lines)


# ── Registry ─────────────────────────────────────────────────────────


THEME_REGISTRY: list[Theme] = [
    ClassicTheme(),
    HardwareTheme(),
    ObservatoryTheme(),
    ZenTheme(),
    NarrativeTheme(),
    FleetTheme(),
    MemoryPalaceTheme(),
    EconomicsTheme(),
    GitForgeTheme(),
    HeartbeatTheme(),
    ArchaeologistTheme(),
    RiceTheme(),
    GpuTheme(),
    GridTheme(),
    ClassicGridTheme(),
    GpuGridTheme(),
]


def get_theme(index: int) -> Theme:
    """DEPRECATED: Use get_theme_by_name() instead.

    Numeric indices are fragile — adding/removing themes changes all indices.
    This function remains for backward compatibility during migration.
    """
    import sys
    sys.stderr.write("statusline: get_theme(index) is deprecated, use get_theme_by_name()\n")
    if 0 <= index < len(THEME_REGISTRY):
        return THEME_REGISTRY[index]
    return THEME_REGISTRY[0]


def get_theme_by_name(name: str) -> Optional[Theme]:
    """Get a theme by name. Returns None if not found."""
    _ensure_themes_validated()
    for theme in THEME_REGISTRY:
        if theme.name == name:
            return theme
    return None


_themes_validated = False


def _ensure_themes_validated() -> None:
    """Lazy validation: verify all theme component requirements are satisfiable."""
    global _themes_validated
    if _themes_validated:
        return
    _themes_validated = True
    try:
        from components import COMPONENT_REGISTRY
        for theme in THEME_REGISTRY:
            for comp in theme.required_components():
                if comp not in COMPONENT_REGISTRY:
                    import sys
                    sys.stderr.write(
                        f"statusline: theme '{theme.name}' requires unknown component '{comp}'\n"
                    )
    except ImportError:
        pass  # Components not available yet (shouldn't happen)
