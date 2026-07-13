"""Persona metadata loader for claude-statusline.

Reads character + role YAML from the claude-personas plugin and returns
a flat info dict for display. Cache to /tmp with 5-minute TTL — persona
switches are rare so stale data is fine; what matters is zero overhead on
every 300ms statusline render.

Never crashes — returns safe defaults on any failure.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

from state import _parse_yaml_simple


def _atomic_write_text(path: Path, content: str) -> None:
    """POSIX-atomic write via temp file + rename in the same directory.

    Matches the pattern used by net_utils, state, subprocess_caps, and
    grid_io. Required for /tmp caches read at the 300ms render cadence:
    a bare write_text would let a concurrent reader observe a truncated
    JSON file, forcing every reader during the race window to fall
    through to a cold DB load.
    """
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.rename(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

# claude-emoji canonical glyph database. Persona glyphs live under
# entity_key='persona:<slug>'. Statusline reads, does not write.
EMOJI_DB_PATH = Path.home() / ".claude" / "local" / "emoji" / "emoji.db"


def _discover_personas_plugin_root() -> Path:
    """Locate the optional claude-personas plugin, if installed.

    Resolution order:
      1. $CLAUDE_PERSONAS_ROOT — explicit override
      2. Siblings under $CLAUDE_PLUGIN_ROOT's parent (marketplace install)
      3. A fallback path that will simply not exist — callers tolerate this
         and return default persona info, so no crash.
    """
    override = os.environ.get("CLAUDE_PERSONAS_ROOT")
    if override:
        return Path(override)

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        # Marketplace layout: <marketplace>/<plugin>/<version>/
        # Sibling plugin lives at <marketplace>/claude-personas/<version>/
        here = Path(plugin_root).resolve()
        marketplace = here.parent.parent
        candidates = sorted(
            marketplace.glob("claude-personas/*/"),
            reverse=True,  # newest version first
        )
        if candidates:
            return candidates[0]

    # Non-existent default — callers degrade gracefully.
    return Path.home() / ".claude" / "plugins" / "claude-personas"


PERSONAS_PLUGIN_ROOT = _discover_personas_plugin_root()
CACHE_FILE = Path("/tmp/statusline-persona.json")
CACHE_TTL_SECONDS = 300  # 5 minutes

_DEFAULT_INFO: Dict[str, Any] = {
    "slug": "claude",
    "name": "Claude",
    "role_slug": "",
    "role_name": "",
    "color": "",          # empty = use theme accent
    "model": "",
    "agency_level": 0,
    "group": "",
    "tools_count": 0,
    "knowledge_count": 0,
    "backends_count": 0,
    "icon": "",           # claude-emoji glyph; empty triggers renderer fallback
}


def _load_persona_icon(slug: str) -> str:
    """Look up the persona's signature glyph in the claude-emoji DB.

    Returns the emoji string for `persona:<slug>` or "" if the DB is
    unreachable / the slug has no mapping. Never raises.

    The query is a single indexed SELECT (idx_emoji_category) — sub-ms.
    Caller is responsible for caching (handled by the /tmp persona-info
    cache in get_persona_info).
    """
    if not slug or slug == "claude":
        return ""
    if not EMOJI_DB_PATH.exists():
        return ""
    try:
        with sqlite3.connect(f"file:{EMOJI_DB_PATH}?mode=ro", uri=True, timeout=0.25) as conn:
            row = conn.execute(
                "SELECT emoji FROM emoji_mappings WHERE entity_key = ? LIMIT 1",
                (f"persona:{slug}",),
            ).fetchone()
            return row[0] if row else ""
    except (sqlite3.Error, OSError):
        return ""


def _load_persona(slug: str) -> Dict[str, Any]:
    """Load persona from character + role YAML files."""
    info = dict(_DEFAULT_INFO)
    info["slug"] = slug

    # Resolve glyph from claude-emoji canonical DB first so every early-
    # return path below still produces an icon when one is registered.
    info["icon"] = _load_persona_icon(slug)

    if slug == "claude" or not slug:
        return info

    # Load character YAML
    char_path = (
        PERSONAS_PLUGIN_ROOT / "personas" / "characters" / f"{slug}.character.yaml"
    )
    if not char_path.exists():
        return info

    try:
        char = _parse_yaml_simple(char_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return info

    # Extract identity fields
    identity = char.get("identity", {})
    if isinstance(identity, dict):
        info["name"] = identity.get("name", slug.title())
        info["agency_level"] = identity.get("agency_level", 0)
        info["group"] = identity.get("group", "")
    else:
        info["name"] = slug.title()

    # Find role slug — check top-level then identity sub-key
    role_slug = char.get("role", "")
    if not role_slug and isinstance(identity, dict):
        role_slug = identity.get("role", "")

    if not role_slug:
        return info

    info["role_slug"] = role_slug

    # Load role YAML
    role_path = (
        PERSONAS_PLUGIN_ROOT / "personas" / "roles" / f"{role_slug}.role.yaml"
    )
    if not role_path.exists():
        return info

    try:
        role = _parse_yaml_simple(role_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return info

    # Extract role fields
    info["role_name"] = role.get("name", "")

    caps = role.get("capabilities", {})
    if isinstance(caps, dict):
        info["color"] = caps.get("color", "")
        info["model"] = caps.get("model", "")

        # Count tools — _parse_yaml_simple doesn't handle YAML lists, so this
        # is best-effort. If tools parses as a dict of named entries, count them.
        tools = caps.get("tools", {})
        if isinstance(tools, dict):
            info["tools_count"] = len(tools)

    # Count knowledge references
    knowledge = role.get("knowledge", {})
    if isinstance(knowledge, dict):
        refs = knowledge.get("references", {})
        if isinstance(refs, dict):
            info["knowledge_count"] = len(refs)

    # Count backends
    backends = role.get("backends", {})
    if isinstance(backends, dict):
        info["backends_count"] = len(backends)

    return info


def get_persona_info(slug: str) -> Dict[str, Any]:
    """Get persona data with 5-minute cache.

    Args:
        slug: Persona slug (e.g. "matt", "claude"). Use "claude" for the
              default Claude identity (no character file needed).

    Returns:
        Flat dict with identity + role fields. Always returns a complete
        dict — never raises.
    """
    # 1. Check cache — must match slug AND be within TTL
    try:
        if CACHE_FILE.exists():
            stat = CACHE_FILE.stat()
            if time.time() - stat.st_mtime < CACHE_TTL_SECONDS:
                data = json.loads(CACHE_FILE.read_text())
                if isinstance(data, dict) and data.get("slug") == slug:
                    return data
    except (OSError, json.JSONDecodeError):
        pass

    # 2. Compute fresh
    info = _load_persona(slug)

    # 3. Write cache (best-effort, atomic — see _atomic_write_text).
    try:
        _atomic_write_text(CACHE_FILE, json.dumps(info))
    except OSError:
        pass

    return info
