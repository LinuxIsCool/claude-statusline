---
name: statusline-master
description: >
  Dashboard statusline — 12 themes × 9 color palettes with full payload logging,
  persona awareness, memory integration, and session lifecycle tracking.
  Use when the user wants to change themes, check statusline health, configure display,
  or understand what the statusline shows.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

## Philosophy

Stream transformer — JSON in, ANSI out, log everything. Themes never touch raw payloads; components compute data, themes format it. The statusline is not decoration: it is a continuous read of the machine's cognitive state, rendered line by line at the bottom of every session.

## Architecture Overview

Hooks (session_start, user_prompt, session_stop) fire → StatusPayload parsed from hook event JSON → 17 components computed on-demand (persona, model, context, cost, rates, memory counts, session number, git state, fleet health, etc.) → Active theme renders components to ANSI strings (12 themes × 9 palettes = 99 possible combinations) → output written to the statusline. Side effect on every event: dual JSONL+SQLite logging for historical analysis and trend detection.

## Data Locations

| Path | Purpose |
|------|---------|
| `~/.claude/local/statusline/state.json` | Live state: current theme, palette, session info, memory cache |
| `~/.claude/local/statusline/events/YYYY-MM.jsonl` | Monthly event log (one JSON object per line) |
| `~/.claude/local/statusline/statusline.db` | SQLite: `events` + `sessions` tables with indexes |
| `~/.claude/local/statusline/config.yaml` | Runtime overrides (user-editable) |
| `${CLAUDE_PLUGIN_ROOT}/config/defaults.yaml` | Shipped defaults (read-only) |

## Subskills

| Trigger | Subskill | Purpose |
|---------|----------|---------|
| `theme`, `theme-cycle`, next/prev/set/list theme | @theme-cycle | Change data theme |
| `color`, `color-cycle`, next/prev/set/list color | @color-cycle | Change color palette independently |
| `status`, `health`, `check`, no args | @status-check | Show statusline health, stats, config |
| `configure`, `config`, `set` | @configure | View/set configuration defaults |
| `memory`, `memory-status`, `backends` | @memory-status | Query memory backends, force refresh |

## Routing

- No args → delegate to @status-check
- First arg matches a subskill trigger → route there
- Unknown arg → show this help with the Quick Reference table

## Quick Reference

| Command | Action |
|---------|--------|
| `/statusline:theme [next\|prev\|set\|list]` | Cycle data themes |
| `/statusline:color [next\|prev\|set\|list]` | Cycle color palettes |
| `/statusline:status` | Show current config + stats |
| `/statusline:configure [show\|set\|reset]` | Manage config |
