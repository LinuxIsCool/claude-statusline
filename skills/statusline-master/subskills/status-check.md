---
name: status-check
description: Show statusline health, configuration, and statistics
---

## Implementation

Run these queries and present a formatted summary:

### 1. Read live state

```bash
cat ~/.claude/local/statusline/state.json
```

### 2. Count JSONL events

```bash
wc -l ~/.claude/local/statusline/events/*.jsonl 2>/dev/null
```

### 3. Count SQLite events

```bash
sqlite3 ~/.claude/local/statusline/statusline.db "SELECT count(*) FROM events"
```

### 4. Count sessions

```bash
sqlite3 ~/.claude/local/statusline/statusline.db "SELECT count(*) FROM sessions"
```

### 5. Latest event timestamp

```bash
sqlite3 ~/.claude/local/statusline/statusline.db "SELECT datetime(timestamp_us/1000000, 'unixepoch', 'localtime') FROM events ORDER BY id DESC LIMIT 1"
```

### 6. Memory cache

Extract `memory_cache` from state.json — show each backend name and count.

### 7. Active sessions

Extract active session list from state.json.

## Output Format

Present as four sections:

**Display** — Active theme (name + #), active palette (name + #), nerd_font enabled/disabled, lines per render.

**Logging** — JSONL event count by month, SQLite event total, SQLite session total, timestamp of most recent event.

**Memory** — Each of 7 backends with count and cache age (derive from `memory_refresh_counter × 300ms`).

**Sessions** — Active session IDs, current persona, current session number.

If state.json does not exist, report "Statusline not yet initialized — no session has fired."
If SQLite does not exist, report logging counts as 0 and note DB has not been created yet.
