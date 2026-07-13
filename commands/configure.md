---
name: configure
description: "View or set statusline configuration defaults"
argument-hint: "[show | set <key> <value> | reset]"
allowed-tools: ["Bash", "Read", "Write"]
---

# /statusline:configure

Manage statusline configuration. Defaults ship with the plugin; runtime overrides are stored per-user.

## Usage

| Command | Action |
|---------|--------|
| `/statusline:configure` | Same as `show` |
| `/statusline:configure show` | Display current config (merged defaults + overrides) |
| `/statusline:configure set <key> <value>` | Set a config value |
| `/statusline:configure reset` | Remove all runtime overrides (revert to defaults) |

## Configurable Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `display.default_theme` | string | classic | Theme on fresh sessions |
| `display.default_color` | string | catppuccin_mocha | Color on fresh sessions |
| `display.nerd_font` | bool | true | Use NerdFont icons |
| `memory.refresh_interval` | int | 60 | Status events between backend refreshes |
| `memory.query_timeout` | float | 2.0 | Seconds per backend query |
| `logging.retention_days` | int | 90 | Auto-prune events older than N days |
| `sessions.stale_hours` | int | 24 | Remove idle sessions after N hours |
| `sessions.title_inference` | bool | true | Infer session title from first prompt |
| `git.cache_ttl` | int | 10 | Seconds to cache git info |
| `components.gpu` | bool | true | Show GPU metrics (nvidia-smi) |
| `components.memory` | bool | true | Show memory backend counts |
| `components.git` | bool | true | Show git branch/status |
| `components.topics` | bool | true | Show topic history |
| `components.sessions` | bool | true | Show active sessions |

## Config Locations

- **Defaults (read-only)**: `${CLAUDE_PLUGIN_ROOT}/config/defaults.yaml`
- **Runtime overrides**: `~/.claude/local/statusline/config.yaml`

## Implementation

Read both YAML files, deep merge (runtime overrides defaults), display or modify.

```bash
# Show merged config
python3 -c "
import yaml, os
from pathlib import Path

defaults_path = Path(os.environ.get('CLAUDE_PLUGIN_ROOT', '.')) / 'config/defaults.yaml'
overrides_path = Path.home() / '.claude/local/statusline/config.yaml'

defaults = yaml.safe_load(defaults_path.read_text()) if defaults_path.exists() else {}
overrides = yaml.safe_load(overrides_path.read_text()) if overrides_path.exists() else {}

def deep_merge(base, over):
    result = dict(base)
    for k, v in over.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result

merged = deep_merge(defaults, overrides)
print(yaml.dump(merged, default_flow_style=False))
" 2>/dev/null
```
