#!/usr/bin/env python3
"""Portable theme & color cycling — zero external deps, works on any OS/DE.

Usage:
    cycle_theme.py              # next theme
    cycle_theme.py next         # next theme
    cycle_theme.py prev         # previous theme
    cycle_theme.py set <name>   # switch to named theme
    cycle_theme.py list         # list all themes with current highlighted

    cycle_theme.py color next       # next color palette
    cycle_theme.py color prev       # previous color palette
    cycle_theme.py color set <name> # switch to named palette
    cycle_theme.py color list       # list all palettes with current highlighted

    cycle_theme.py status       # show current theme + color scheme

Themes are stored by NAME in state.json (not positional index).
Uses merge-write to avoid clobbering concurrent status.py writes.
"""

import fcntl
import json
import os
import sys
import tempfile
from pathlib import Path

STATE_PATH = Path.home() / ".claude" / "local" / "statusline" / "state.json"
LOCK_PATH = STATE_PATH.with_suffix(".lock")

# Theme names — order only matters for next/prev cycling, not for storage.
# Adding/removing/reordering here does NOT corrupt existing state because
# state.json stores the theme name, not a positional index.
# NOTE: Keep in sync with THEME_REGISTRY in lib/themes.py.
THEMES = [
    "classic",
    "hw",
    "observatory",
    "zen",
    "narrative",
    "fleet",
    "memory_palace",
    "economics",
    "git_forge",
    "heartbeat",
    "archaeologist",
    "rice",
    "gpu",
    "grid",
    "classic+grid",
    "gpu+grid",
]

THEME_DESCRIPTIONS = {
    "classic": "Original Phase 1 — the one you saw first",
    "hw": "Minimal hardware — CPU/GPU/wifi vitals in 5 lines",
    "observatory": "Full data dashboard — ALL fields displayed",
    "zen": "Minimalist — persona + context bar only",
    "narrative": "Topic timeline — session story",
    "fleet": "Multi-agent — all active sessions",
    "memory_palace": "Memory backends — counts per backend",
    "economics": "Cost-focused — burn rate, budget",
    "git_forge": "Code-centric — branch, diff stats",
    "heartbeat": "Health monitor — context, rate limits, sparklines",
    "archaeologist": "Session history — notes, cross-references",
    "rice": "Pure aesthetics — powerline, NerdFont",
    "gpu": "Classic + nvidia-smi — GPU util, VRAM, temp, power, processes",
    "grid": "Timeline grid — activity heatmap",
    "classic+grid": "Classic + timeline grid section",
    "gpu+grid": "GPU dashboard + timeline grid section",
}

# Color palette names — order matters for next/prev cycling.
COLOR_SCHEMES = [
    "catppuccin_mocha",
    "catppuccin_macchiato",
    "catppuccin_frappe",
    "catppuccin_latte",
    "nord_frost",
    "nord_aurora",
    "nord_polar",
    "solarized_dark",
    "solarized_light",
]

COLOR_DESCRIPTIONS = {
    "catppuccin_mocha": "Catppuccin Mocha — warm dark (default)",
    "catppuccin_macchiato": "Catppuccin Macchiato — medium dark",
    "catppuccin_frappe": "Catppuccin Frappe — cool dark",
    "catppuccin_latte": "Catppuccin Latte — light mode",
    "nord_frost": "Nord Frost — arctic blue dark",
    "nord_aurora": "Nord Aurora — warm accents dark",
    "nord_polar": "Nord Polar Night — deep muted dark",
    "solarized_dark": "Solarized Dark — classic dark",
    "solarized_light": "Solarized Light — classic light",
}


def _load_state_raw() -> dict:
    """Load full state from disk, no defaults applied."""
    try:
        if STATE_PATH.exists():
            with open(STATE_PATH) as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _atomic_write(state: dict) -> None:
    """Atomic write via tmpfile + rename."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=STATE_PATH.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
            f.write("\n")
        os.rename(tmp, STATE_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def merge_write(updates: dict) -> dict:
    """Read-modify-write under file lock to avoid race with status.py.

    Returns the merged state for display purposes.
    """
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_PATH, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = _load_state_raw()
        state.update(updates)
        _atomic_write(state)
    return state


def _resolve_theme_name(state: dict) -> str:
    """Get current theme name from state, handling legacy index migration."""
    name = state.get("theme")
    if name and name in THEMES:
        return name
    # Legacy: migrate from theme_index
    idx = state.get("theme_index", 0)
    return THEMES[idx % len(THEMES)]


def _cycle_color(args: list[str], state: dict) -> None:
    """Handle 'color' subcommand."""
    sub = args[0] if args else "next"
    current_name = state.get("color_scheme", "catppuccin_mocha")
    try:
        current_idx = COLOR_SCHEMES.index(current_name)
    except ValueError:
        current_idx = 0

    if sub == "list":
        for i, name in enumerate(COLOR_SCHEMES):
            marker = "→" if i == current_idx else " "
            desc = COLOR_DESCRIPTIONS.get(name, "")
            print(f"  {marker} {i}: {name:24s} {desc}")
        return

    if sub == "set":
        if len(args) < 2:
            print("Usage: cycle_theme.py color set <palette-name>", file=sys.stderr)
            sys.exit(1)
        target = args[1].lower()
        matches = [i for i, c in enumerate(COLOR_SCHEMES) if c.startswith(target)]
        if not matches:
            print(f"Unknown palette: {target}", file=sys.stderr)
            print(f"Available: {', '.join(COLOR_SCHEMES)}", file=sys.stderr)
            sys.exit(1)
        new_idx = matches[0]
    elif sub == "prev":
        new_idx = (current_idx - 1) % len(COLOR_SCHEMES)
    else:  # "next" or default
        new_idx = (current_idx + 1) % len(COLOR_SCHEMES)

    new_name = COLOR_SCHEMES[new_idx]
    merged = merge_write({"color_scheme": new_name})

    desc = COLOR_DESCRIPTIONS.get(new_name, "")
    theme_name = _resolve_theme_name(merged)
    print(f"Color: {new_name} ({new_idx}/{len(COLOR_SCHEMES)-1}) — {desc}")
    print(f"Theme: {theme_name}")


def main() -> None:
    args = sys.argv[1:]
    cmd = args[0] if args else "next"

    state = _load_state_raw()

    # Color subcommand
    if cmd == "color":
        _cycle_color(args[1:], state)
        return

    # Status subcommand
    if cmd == "status":
        theme_name = _resolve_theme_name(state)
        color_name = state.get("color_scheme", "catppuccin_mocha")
        print(f"Theme: {theme_name} — {THEME_DESCRIPTIONS.get(theme_name, '')}")
        print(f"Color: {color_name} — {COLOR_DESCRIPTIONS.get(color_name, '')}")
        return

    current_name = _resolve_theme_name(state)
    try:
        current_idx = THEMES.index(current_name)
    except ValueError:
        current_idx = 0

    if cmd == "list":
        color_name = state.get("color_scheme", "catppuccin_mocha")
        print(f"  Color scheme: {color_name}")
        print()
        for i, name in enumerate(THEMES):
            marker = "→" if name == current_name else " "
            desc = THEME_DESCRIPTIONS.get(name, "")
            print(f"  {marker} {i}: {name:16s} {desc}")
        return

    if cmd == "set":
        if len(args) < 2:
            print("Usage: cycle_theme.py set <theme-name>", file=sys.stderr)
            sys.exit(1)
        target = args[1].lower()
        matches = [t for t in THEMES if t.startswith(target)]
        if not matches:
            print(f"Unknown theme: {target}", file=sys.stderr)
            print(f"Available: {', '.join(THEMES)}", file=sys.stderr)
            sys.exit(1)
        new_name = matches[0]
    elif cmd == "prev":
        new_idx = (current_idx - 1) % len(THEMES)
        new_name = THEMES[new_idx]
    else:  # "next" or default
        new_idx = (current_idx + 1) % len(THEMES)
        new_name = THEMES[new_idx]

    # Merge-write: only touch the keys we own, don't clobber status.py's state
    merge_write({"theme": new_name})

    desc = THEME_DESCRIPTIONS.get(new_name, "")
    color_name = state.get("color_scheme", "catppuccin_mocha")
    print(f"Theme: {new_name} — {desc}")
    print(f"Color: {color_name}")


if __name__ == "__main__":
    main()
