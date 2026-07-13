"""Memory backend queries for claude-statusline.

Each function queries one backend and returns an int count or "?" on failure.
All queries have timeouts — they must never block the render path.
Stdlib only: subprocess, urllib, sqlite3, glob, pathlib.
"""

from __future__ import annotations

import glob
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Callable, Union
from urllib.request import urlopen
from urllib.error import URLError

CountOrUnknown = Union[int, str]
BackendQueryFn = Callable[[], CountOrUnknown]

# ── Configurable endpoints (override via environment) ─────────────────

# FalkorDB / Hippo knowledge graph
HIPPO_CONTAINER = os.environ.get("STATUSLINE_HIPPO_CONTAINER", "hippo-graph")
HIPPO_REDIS_PORT = os.environ.get("STATUSLINE_HIPPO_PORT", "6379")
HIPPO_GRAPH_NAME = os.environ.get("STATUSLINE_HIPPO_GRAPH", "hippo")

# KOI bundle store (PostgreSQL)
KOI_DB = os.environ.get("STATUSLINE_KOI_DB", "koi")

# Letta agent server
LETTA_URL = os.environ.get("STATUSLINE_LETTA_URL", "http://localhost:8283")

# ── Backend query functions ──────────────────────────────────────────


def query_hippo() -> CountOrUnknown:
    """Count Hippo graph nodes. FalkorDB container (configurable)."""
    try:
        result = subprocess.run(
            ["docker", "exec", HIPPO_CONTAINER, "redis-cli", "-p", HIPPO_REDIS_PORT,
             "GRAPH.QUERY", HIPPO_GRAPH_NAME, "MATCH (n) RETURN count(n)"],
            capture_output=True, text=True, timeout=2.0,
        )
        if result.returncode != 0:
            return "?"
        # redis-cli with human-readable output returns:
        #   count(n)
        #   10931
        #   Cached execution: 1
        #   Query internal execution time: ...
        # Skip the header line ("count(n)") and parse the first integer line.
        lines = result.stdout.splitlines()
        past_header = False
        for line in lines:
            stripped = line.strip()
            if not past_header:
                # Skip the column name header
                past_header = True
                continue
            if stripped.isdigit():
                return int(stripped)
        # Fallback: also try "(integer) N" format (RESP2 raw output)
        for line in lines:
            if "(integer)" in line:
                parts = line.split("(integer)")
                if len(parts) > 1:
                    num = parts[1].strip().rstrip(")")
                    if num.isdigit():
                        return int(num)
        return "?"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return "?"


def query_koi() -> CountOrUnknown:
    """Count KOI bundles. PostgreSQL database (configurable via STATUSLINE_KOI_DB)."""
    try:
        result = subprocess.run(
            ["psql", "-t", "-A", "-c", "SELECT count(*) FROM bundles", KOI_DB],
            capture_output=True, text=True, timeout=2.0,
        )
        if result.returncode != 0:
            return "?"
        count_str = result.stdout.strip()
        if count_str.isdigit():
            return int(count_str)
        return "?"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return "?"


def query_journal() -> CountOrUnknown:
    """Count journal markdown entries."""
    try:
        journal_dir = Path.home() / ".claude" / "local" / "journal"
        if not journal_dir.exists():
            return 0
        entries = glob.glob(str(journal_dir / "**" / "*.md"), recursive=True)
        return len(entries)
    except OSError:
        return "?"


def query_letta() -> CountOrUnknown:
    """Check Letta server health. Returns 1 if healthy, 0 if not.

    Override the endpoint with STATUSLINE_LETTA_URL.
    """
    try:
        resp = urlopen(f"{LETTA_URL.rstrip('/')}/v1/health", timeout=1.0)
        if resp.status == 200:
            return 1
        return 0
    except (URLError, OSError, TimeoutError):
        return 0


def query_messages() -> CountOrUnknown:
    """Count messages in messages DB."""
    try:
        db_path = Path.home() / ".claude" / "local" / "messages" / "messages.db"
        if not db_path.exists():
            return 0
        conn = sqlite3.connect(str(db_path), timeout=1.0)
        try:
            row = conn.execute("SELECT count(*) FROM messages").fetchone()
            return row[0] if row else 0
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return "?"


def query_files() -> CountOrUnknown:
    """Count research + knowledge markdown files."""
    try:
        research_dir = Path.home() / ".claude" / "local" / "research"
        if not research_dir.exists():
            return 0
        entries = glob.glob(str(research_dir / "**" / "*.md"), recursive=True)
        return len(entries)
    except OSError:
        return "?"


def query_sessions() -> CountOrUnknown:
    """Count session transcript files across all project dirs.

    Claude Code stores transcripts under ~/.claude/projects/<encoded-cwd>/*.jsonl
    where <encoded-cwd> is the absolute cwd with slashes replaced by dashes.
    Count across every project dir so this works regardless of user/home path.
    """
    try:
        projects_dir = Path.home() / ".claude" / "projects"
        if not projects_dir.exists():
            return 0
        entries = glob.glob(str(projects_dir / "*" / "*.jsonl"))
        return len(entries)
    except OSError:
        return "?"


# ── Backend registry (name, query function) ──────────────────────────

BACKENDS: list[tuple[str, BackendQueryFn]] = [
    ("hippo", query_hippo),
    ("koi", query_koi),
    ("journal", query_journal),
    ("letta", query_letta),
    ("messages", query_messages),
    ("files", query_files),
    ("sessions", query_sessions),
]


def query_all() -> dict:
    """Query all backends. Returns {name: count_or_?, total: int_or_?}."""
    result = {}
    for name, fn in BACKENDS:
        try:
            result[name] = fn()
        except Exception as e:
            import sys as _sys
            _sys.stderr.write(f"statusline: memory query {name}: {e}\n")
            result[name] = "?"

    # Compute total from all integer values
    int_values = [v for v in result.values() if isinstance(v, int)]
    result["total"] = sum(int_values) if int_values else "?"
    return result
