---
name: memory-status
description: Query memory backends, force refresh, or debug a specific backend
---

## Implementation

### Default (no args)

Read `memory_cache` from state.json and display all 7 backend counts with cache age.

Cache age = `memory_refresh_counter` (from state.json) × 300ms — this is approximate staleness.

```bash
cat ~/.claude/local/statusline/state.json | python3 -c "
import json, sys
state = json.load(sys.stdin)
cache = state.get('memory_cache', {})
counter = state.get('memory_refresh_counter', 0)
age_s = counter * 0.3
print(f'Cache age: ~{age_s:.0f}s ({counter} events ago)')
for k, v in cache.items():
    print(f'  {k}: {v}')
"
```

### `refresh` (all backends)

Force-query all 7 backends live and display results:

```bash
cd ${CLAUDE_PLUGIN_ROOT} && python3 -c "
import sys; sys.path.insert(0, 'lib')
from memory import query_all
import json
print(json.dumps(query_all(), indent=2))
"
```

### `refresh <backend>`

Refresh a single named backend. Valid names:

| Backend | Source | What it counts |
|---------|--------|----------------|
| `hippo` | FalkorDB graph | Node count in `hippo` graph |
| `koi` | PostgreSQL (`STATUSLINE_KOI_DB`, default `koi`) | Bundle count across all namespaces |
| `journal` | Markdown files | Files in `~/.claude/local/journal/` |
| `letta` | HTTP health check | Letta server reachable (1) or not (0) |
| `messages` | SQLite | Message count in messages DB |
| `files` | Filesystem | Research markdown files in `~/.claude/local/research/` |
| `sessions` | Filesystem | JSONL transcript files in `~/.claude/projects/` |

Run single backend:

```bash
cd ${CLAUDE_PLUGIN_ROOT} && python3 -c "
import sys; sys.path.insert(0, 'lib')
from memory import query_backend
import json
print(json.dumps(query_backend('BACKEND_NAME'), indent=2))
"
```

Replace `BACKEND_NAME` with the requested backend.

## Notes

- Memory counts in state.json are updated on a background cadence (every N events, configurable via `memory.refresh_interval`)
- If a backend is unreachable (e.g., Letta down, FalkorDB container stopped), its count will be 0 or None — not an error
- `refresh` hits the live sources directly, bypassing the cache — useful for debugging stale counts
