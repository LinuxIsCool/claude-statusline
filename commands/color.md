---
name: color
description: "Cycle color palettes independently of data themes"
argument-hint: "[next | prev | set <name> | list]"
allowed-tools: ["Bash", "Read"]
---

# /statusline:color

Switch between the 9 color palettes. Color is independent of data theme — any palette works with any theme.

## Usage

| Command | Action |
|---------|--------|
| `/statusline:color` | Show current palette and list all available |
| `/statusline:color next` | Switch to next palette |
| `/statusline:color prev` | Switch to previous palette |
| `/statusline:color set <name>` | Switch to named palette (prefix match) |
| `/statusline:color list` | List all palettes with descriptions |

## Implementation

Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cycle_theme.py color $ARGS`. If no arg, run `color list`.

## Available Palettes

| # | Name | Family | Tone |
|---|------|--------|------|
| 0 | catppuccin_mocha | Catppuccin | Warm dark (default) |
| 1 | catppuccin_macchiato | Catppuccin | Medium dark |
| 2 | catppuccin_frappe | Catppuccin | Cool dark |
| 3 | catppuccin_latte | Catppuccin | Light |
| 4 | nord_frost | Nord | Arctic blue |
| 5 | nord_aurora | Nord | Warm accents |
| 6 | nord_polar | Nord | Deep muted |
| 7 | solarized_dark | Solarized | Classic dark |
| 8 | solarized_light | Solarized | Classic light |

Each theme has a default palette. If you haven't set a color explicitly, the theme's preferred palette is used. Once you set a color, it persists across theme changes.
