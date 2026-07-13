---
name: color-cycle
description: Cycle through color palettes independently of data themes
---

## Implementation

Run the cycle script with the `color` subcommand:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cycle_theme.py color $ARGS
```

Usage: `next`, `prev`, `set <name>`, `list`

## Available Palettes

| # | Name | Family | Tone |
|---|------|--------|------|
| 0 | catppuccin_mocha | Catppuccin | Warm dark |
| 1 | catppuccin_macchiato | Catppuccin | Medium dark |
| 2 | catppuccin_frappe | Catppuccin | Cool dark |
| 3 | catppuccin_latte | Catppuccin | Light |
| 4 | nord_frost | Nord | Arctic blue |
| 5 | nord_aurora | Nord | Warm accents |
| 6 | nord_polar | Nord | Deep muted |
| 7 | solarized_dark | Solarized | Classic dark |
| 8 | solarized_light | Solarized | Classic light |

## Notes

- Any palette works with any data theme — they are fully orthogonal
- If no palette override is set, each theme uses its own default palette
- Setting a palette override persists across theme changes
- To revert to per-theme defaults, reset the palette override in config
