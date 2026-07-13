"""Map Claude Code events to emoji grid cells.

DRY: emoji glyphs come from claude-emoji's emoji_flat.json export.
This module only maps Claude Code event/tool names to emoji DB keys.
It never defines an emoji — only looks them up.

Usage:
    emoji, key = map_event("PreToolUse", tool_name="Read")
    weight = get_weight(key)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# ── Emoji flat file (read once, cached) ─────────────────────────────

_FLAT_PATH = Path.home() / ".claude" / "local" / "emoji" / "emoji_flat.json"
_flat_cache: Optional[dict[str, str]] = None
_flat_mtime: float = 0.0
_GLOBAL_FALLBACK = "❓"


def _load_flat() -> dict[str, str]:
    """Load emoji_flat.json. Cached with mtime invalidation.

    If the file's modification time changes (e.g., after emoji DB re-export),
    the cache is reloaded automatically. No manual restart needed.
    """
    global _flat_cache, _flat_mtime
    try:
        current_mtime = _FLAT_PATH.stat().st_mtime if _FLAT_PATH.exists() else 0.0
    except OSError:
        current_mtime = 0.0

    if _flat_cache is not None and current_mtime == _flat_mtime:
        return _flat_cache

    try:
        _flat_cache = json.loads(_FLAT_PATH.read_text(encoding="utf-8"))
        _flat_mtime = current_mtime
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        _flat_cache = {}
        _flat_mtime = 0.0
    return _flat_cache or {}


# ── Claude Code event name → emoji DB key ───────────────────────────

EVENT_KEY_MAP: dict[str, str] = {
    "SessionStart":       "event:session-start",
    "SessionEnd":         "event:session-end",
    "UserPromptSubmit":   "event:user-prompt-submit",
    "Stop":               "event:stop",
    "StopFailure":        "event:stop-failure",
    "PreToolUse":         "event:pre-tool-use",
    "PostToolUse":        "event:post-tool-use",
    "PostToolUseFailure": "event:post-tool-use-failure",
    "PermissionRequest":  "event:permission-request",
    "SubagentStart":      "event:subagent-start",
    "SubagentStop":       "event:subagent-stop",
    "PreCompact":         "event:pre-compact",
    "PostCompact":        "event:post-compact",
    "Notification":       "event:notification",
    "Elicitation":        "event:elicitation",
    "ElicitationResult":  "event:elicitation-result",
    "TaskCreated":        "event:task-created",
    "TaskCompleted":      "event:task-completed",
    "TeammateIdle":       "event:teammate-idle",
    "InstructionsLoaded": "event:instructions-loaded",
    "ConfigChange":       "event:config-change",
    "CwdChanged":         "event:cwd-changed",
    "FileChanged":        "event:file-changed",
    "WorktreeCreate":     "event:worktree-create",
    "WorktreeRemove":     "event:worktree-remove",
}


# ── Claude Code tool name → emoji DB key ────────────────────────────

TOOL_KEY_MAP: dict[str, str] = {
    "Read":         "tool:read",
    "Write":        "tool:write",
    "Edit":         "tool:edit",
    "Bash":         "tool:bash",
    "Glob":         "tool:glob",
    "Grep":         "tool:grep",
    "Agent":        "tool:agent",
    "WebSearch":    "tool:websearch",
    "WebFetch":     "tool:webfetch",
    "Skill":        "tool:skill",
    "SendMessage":  "tool:sendmessage",
    "TodoWrite":    "tool:todowrite",
    "NotebookEdit": "tool:notebookedit",
}


# ── Eviction weight by emoji DB key ─────────────────────────────────

WEIGHT_TABLE: dict[str, int] = {
    # User intent — sacred (weight 10)
    "event:user-prompt-submit": 10,

    # Session landmarks (weight 8)
    "event:session-start":    8,
    "event:session-end":      8,
    "event:stop":             8,

    # Structural markers (weight 6)
    "event:subagent-start":   6,
    "event:subagent-stop":    6,
    "event:pre-compact":      6,
    "event:post-compact":     6,

    # Errors worth remembering (weight 4)
    "event:post-tool-use-failure": 4,
    "event:stop-failure":     4,

    # Mutation tools (weight 3)
    "tool:bash":              3,
    "tool:write":             3,
    "tool:edit":              3,

    # Delegation (weight 2)
    "tool:skill":             2,
    "tool:agent":             2,
    "tool:sendmessage":       2,
    "tool:todowrite":         2,
    "tool:notebookedit":      2,
    "tool:websearch":         2,
    "tool:webfetch":          2,

    # Read-only tools — most common, most evictable (weight 1)
    "tool:read":              1,
    "tool:glob":              1,
    "tool:grep":              1,
}

DEFAULT_WEIGHT = 2


# ── Public API ──────────────────────────────────────────────────────


def map_event(event_type: str, tool_name: Optional[str] = None) -> tuple[str, str]:
    """Map a Claude Code event to (emoji, db_key).

    For PreToolUse/PostToolUse, prefers tool-specific emoji if available.
    Falls back to event-level emoji, then global fallback.
    """
    flat = _load_flat()

    # Tool-specific override for tool events
    if tool_name and event_type in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
        tool_key = TOOL_KEY_MAP.get(tool_name)
        if tool_key and tool_key in flat:
            return flat[tool_key], tool_key

    # Event-level lookup
    event_key = EVENT_KEY_MAP.get(event_type)
    if event_key and event_key in flat:
        return flat[event_key], event_key

    return _GLOBAL_FALLBACK, event_type


def get_weight(key: str) -> int:
    """Get eviction weight for an emoji DB key."""
    return WEIGHT_TABLE.get(key, DEFAULT_WEIGHT)
