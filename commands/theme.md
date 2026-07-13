---
name: theme
description: "Cycle statusline themes or switch to a specific theme"
argument-hint: "[next | prev | set <name> | list]"
allowed-tools: ["Bash", "Read"]
---

# /statusline:theme

Switch between the 12 statusline themes.

## Usage

| Command | Action |
|---------|--------|
| `/statusline:theme` | Show current theme and list all available |
| `/statusline:theme next` | Switch to next theme |
| `/statusline:theme prev` | Switch to previous theme |
| `/statusline:theme set <name>` | Switch to named theme (prefix match) |
| `/statusline:theme list` | List all themes with descriptions |

## Implementation

Run the portable cycle_theme.py script:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cycle_theme.py $ARGS
```

Where `$ARGS` is the subcommand from the user (next, prev, set <name>, list).

If no argument given, run `list` to show current state.

The theme change takes effect on the next Status event (~300ms). No restart needed.

## Available Themes

| # | Name | Lines | Focus |
|---|------|-------|-------|
| 0 | classic | 2 | Original — persona + model + context + rates |
| 1 | observatory | 3 | ALL fields, dense grid |
| 2 | zen | 1 | Minimal — persona + context bar |
| 3 | narrative | 2 | Topic timeline arrows |
| 4 | fleet | 2 | All active sessions |
| 5 | memory_palace | 2 | Memory backend counts |
| 6 | economics | 2 | Cost + burn rate |
| 7 | git_forge | 2 | Branch + diff stats |
| 8 | heartbeat | 2 | Rate limits + health |
| 9 | archaeologist | 2 | Session history |
| 10 | rice | 2 | Powerline aesthetics |
| 11 | gpu | 4 | Classic + nvidia-smi GPU metrics |

**Color palettes** are independent — use `/statusline:color` to change colors without changing the data theme.
