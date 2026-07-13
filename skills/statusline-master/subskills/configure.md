---
name: configure
description: View or set statusline configuration defaults
---

## Implementation

### `show` (or no args)

Read and display merged config: defaults.yaml first, then apply runtime config.yaml overrides on top. Show the final merged result and clearly indicate which keys are overridden at runtime.

```bash
cat ${CLAUDE_PLUGIN_ROOT}/config/defaults.yaml
cat ~/.claude/local/statusline/config.yaml 2>/dev/null || echo "(no runtime overrides)"
```

### `set <key> <value>`

Write a key to the runtime config at `~/.claude/local/statusline/config.yaml` using dot-notation. Create the file if it does not exist.

Common keys:
- `display.nerd_font` — true/false, enables powerline glyphs
- `display.theme` — set default theme name (overridden by cycle_theme.py)
- `display.palette` — set default palette name (overridden by cycle_theme.py)
- `memory.refresh_interval` — how often (in events) to refresh memory counts
- `logging.retention_days` — how many days of JSONL events to keep

### `reset`

Delete the runtime config to revert all settings to shipped defaults:

```bash
rm -f ~/.claude/local/statusline/config.yaml
```

Confirm to the user before deleting. Report "Config reset — all settings reverted to defaults."

## Config Locations

| File | Purpose | Editable |
|------|---------|---------|
| `${CLAUDE_PLUGIN_ROOT}/config/defaults.yaml` | Shipped defaults | No (plugin source) |
| `~/.claude/local/statusline/config.yaml` | Runtime overrides | Yes |

Runtime config takes precedence. Missing keys fall through to defaults.
