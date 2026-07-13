---
name: theme-cycle
description: Cycle through statusline data themes
---

## Implementation

Run the cycle script with user args:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cycle_theme.py $ARGS
```

Usage: `next`, `prev`, `set <name>`, `list`

## Available Themes

| # | Name | Lines | Default Palette | Focus |
|---|------|-------|-----------------|-------|
| 0 | classic | 2 | catppuccin_mocha | Original — persona + model + context + rates |
| 1 | observatory | 3 | catppuccin_mocha | ALL fields, dense grid |
| 2 | zen | 1 | nord_frost | Minimal — persona + context bar |
| 3 | narrative | 2 | solarized_light | Topic timeline with arrows |
| 4 | fleet | 2 | catppuccin_macchiato | Multi-agent view |
| 5 | memory_palace | 2 | catppuccin_mocha | Memory backend counts |
| 6 | economics | 2 | catppuccin_mocha | Cost + burn rate |
| 7 | git_forge | 2 | catppuccin_frappe | Branch + diff stats |
| 8 | heartbeat | 2 | solarized_dark | Rate limits + health |
| 9 | archaeologist | 2 | nord_aurora | Session history |
| 10 | rice | 2 | catppuccin_mocha | Powerline aesthetics |

## Notes

- Changes take effect on next Status event (~300ms delay)
- Color palette is independent — changing theme does NOT reset the active color palette
- Each theme has a default palette but the user's active palette override takes precedence
