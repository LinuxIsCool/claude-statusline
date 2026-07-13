---
description: "Show current statusline configuration and recent stats"
allowed-tools: ["Bash", "Read"]
---

# /statusline:status

Show statusline plugin health: current theme, color scheme, logging stats, and recent payload data.

## Implementation

1. Read state.json:
```bash
cat ~/.claude/local/statusline/state.json 2>/dev/null || echo '{"theme_index": 0}'
```

2. Check JSONL log size:
```bash
wc -l ~/.claude/local/statusline/events/*.jsonl 2>/dev/null
```

3. Check SQLite event count:
```bash
sqlite3 ~/.claude/local/statusline/statusline.db "SELECT count(*) FROM events" 2>/dev/null
```

4. Show latest event timestamp:
```bash
sqlite3 ~/.claude/local/statusline/statusline.db "SELECT datetime(timestamp_us/1000000, 'unixepoch', 'localtime') FROM events ORDER BY id DESC LIMIT 1" 2>/dev/null
```

5. Memory backend counts from state.json:
```bash
python3 -c "import json; s=json.load(open('$HOME/.claude/local/statusline/state.json')); mc=s.get('memory_cache',{}); [print(f'  {k}: {v}') for k,v in mc.items()]" 2>/dev/null
```

6. Active sessions from state.json:
```bash
python3 -c "import json; s=json.load(open('$HOME/.claude/local/statusline/state.json')); sess=s.get('sessions',{}); print(f'{len(sess)} active'); [print(f'  {v.get(\"persona\",\"?\")}:{v.get(\"session_number\",0)} ({k[:8]})') for k,v in sess.items()]" 2>/dev/null
```

7. Event rate (events per hour from recent data):
```bash
sqlite3 ~/.claude/local/statusline/statusline.db "SELECT printf('%.0f events/hr', count(*) * 3600.0 / ((max(timestamp_us) - min(timestamp_us)) / 1000000.0)) FROM events WHERE timestamp_us > (strftime('%s','now') - 3600) * 1000000" 2>/dev/null
```

Present as a summary with sections: **Display** (theme, color), **Logging** (JSONL count, SQLite count, latest event, event rate), **Memory** (backend counts), **Sessions** (active list).
