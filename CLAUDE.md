# claude-statusline

Dashboard statusline for Claude Code: 16 themes × 9 color palettes with hardware telemetry, full payload logging, persona awareness, and session tracking.

**Themes:** `classic`, `hw`, `observatory`, `zen`, `narrative`, `fleet`, `memory_palace`, `economics`, `git_forge`, `heartbeat`, `archaeologist`, `rice`, `gpu`, `grid`, `classic+grid`, `gpu+grid`. (`gpu+grid` and `classic+grid` are real subclasses that append a grid section, not aliases.)

**Palettes:** `catppuccin_mocha` (default), `catppuccin_macchiato`, `catppuccin_frappe`, `catppuccin_latte`, `nord_frost`, `nord_aurora`, `nord_polar`, `solarized_dark`, `solarized_light`.

**Selftest:** `uv run hooks/selftest.py` for runtime capability verification (Python version, wcwidth, /proc/* paths, nvidia-smi, tailscale, nmcli, git, hook imports, theme construction, end-to-end render). Exists as a canary against the PEP-723-vs-dev-venv mismatch class of bug: hooks resolve dependencies from their inline headers, tests from pyproject.toml, and the two must agree.

## Architecture

**Functional Core / Imperative Shell:** `lib/themes.py` contains NO I/O. Every theme renderer is a pure function of `(components, palette) → string`. All env reads, socket calls, getppid, subprocess, and filesystem reads are consolidated in `compute_*` functions in `lib/components.py` at the shell layer.

Key modules:
- `lib/result.py`: `Result[T, E]` type (Ok/Err) for explicit error-channel handling
- `lib/terminal_caps.py`: NO_COLOR, color depth (truecolor/256/16), terminal width, OSC 8 support
- `lib/subprocess_caps.py`: capability blackout pattern (60s skip after subprocess timeout/failure)
- `lib/layout_grid.py`: declarative colspan grid with `Grid.row(cells, align=)` factory; every `│` lands on a fixed column boundary (ANSI-aware, style-preserving truncation enforces this even on overflow)
- `lib/primitives.py`: emoji-aware `visible_len` with a width-override table (terminals disagree with wcwidth about some glyphs; zero-width chars MUST stay width 0 or grid padding breaks), plus `Styled`, a typed (text, visible_width) pair

**Optional integrations (all degrade gracefully when absent):**
- claude-personas checkout for persona colors/metadata (`$CLAUDE_PERSONAS_SRC` or sibling-dir probe; vendored fallback color table in `lib/colors.py`)
- claude-emoji SQLite DB at `~/.claude/local/emoji/emoji.db` for persona glyphs
- thermal DB at `~/.claude/local/thermal/thermal.db` for temperature history
- nvidia-smi / tailscale / nmcli / git: their sections render `—` when missing

**Test suite:** 329 tests (snapshot per theme + property-based via Hypothesis + integration). Run `uv run --extra test pytest`.

**Snapshot regression:** `tests/golden/<theme>.txt` baselines all 16 themes. `UPDATE_SNAPSHOTS=1 pytest tests/test_theme_snapshots.py` to accept new output. Keep mock/fixture data generic: no real SSIDs, IPs, or hostnames.

**Hardening:** atomic /tmp cache writes (race-safe), iface-keyed net prev-snapshot, subprocess blackout for tailscale/nmcli/nvidia-smi/git, process-label ANSI sanitization, defensive wcwidth fallback, expanded ANSI regex (all CSI terminators).

## Quick Start

- `/status` shows current statusline configuration and recent stats
- `/theme [name]` cycles or switches statusline themes
- `/color [name]` cycles color palettes independently
- `/configure` views or sets statusline defaults

## Data Schema

### SQLite: `~/.claude/local/statusline/statusline.db`

```sql
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    timestamp_us INTEGER NOT NULL,
    payload TEXT NOT NULL,
    persona TEXT,
    model TEXT,
    cost_usd REAL,
    context_pct REAL
) STRICT;

CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    persona TEXT NOT NULL,
    session_number INTEGER NOT NULL,
    title TEXT,
    started_at TEXT NOT NULL,
    last_seen TEXT,
    total_cost REAL DEFAULT 0,
    context_peak REAL DEFAULT 0,
    topic_history TEXT,
    prompt_count INTEGER DEFAULT 0
) STRICT;

CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT
) STRICT;
```

### File Layout

```
~/.claude/local/statusline/
  statusline.db              # SQLite (events, sessions, meta)
  state.json                 # Current runtime state (theme, color_scheme, persona, active sessions)
  config.yaml                # Runtime overrides of config/defaults.yaml
  events/
    YYYY-MM.jsonl            # Monthly event log (append-only)
```

### Canonical Counts

```sql
SELECT MAX(session_number) FROM sessions WHERE persona = ?;
```
