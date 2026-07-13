"""Git operations with filesystem caching for claude-statusline.

All operations use subprocess.run with timeout=2s. Cache to /tmp for
10-second TTL. Never crash — returns safe defaults on any failure.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

# subprocess_caps lives in the same lib/ directory.
sys.path.insert(0, str(Path(__file__).parent))
from subprocess_caps import with_blackout  # noqa: E402


CACHE_TTL_SECONDS = 10
CACHE_DIR = Path("/tmp")


def _cache_path(cwd: str) -> Path:
    """Deterministic cache file for a working directory."""
    h = hashlib.md5(cwd.encode()).hexdigest()[:12]
    return CACHE_DIR / f"statusline-git-{h}.json"


def _run_git(args: list[str], cwd: str, timeout: float = 2.0) -> Optional[str]:
    """Run a git command, return stdout or None on failure.

    Guarded by subprocess_caps.with_blackout so a wedged git (corrupted repo,
    NFS-mounted .git, etc.) only costs the first timeout; the next 60s of
    renders skip git invocations entirely and return None as if every call
    failed — same shape callers already handle.
    """
    def _run() -> Optional[str]:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None

    return with_blackout("git", _run, None)


def _compute_git_info(cwd: str) -> Dict[str, Any]:
    """Compute git info from scratch. Called when cache is stale."""
    info: Dict[str, Any] = {
        "branch": "?",
        "dirty": False,
        "ahead": 0,
        "behind": 0,
        "untracked": 0,
        "staged": 0,
        "modified": 0,
        "stash_count": 0,
        "last_commit_msg": "",
        "is_repo": False,
    }

    # Check if we're in a git repo
    toplevel = _run_git(["rev-parse", "--show-toplevel"], cwd)
    if not toplevel:
        return info
    info["is_repo"] = True

    # Branch name
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if branch:
        info["branch"] = branch

    # Status (porcelain v1 — fast, machine-readable)
    status = _run_git(["status", "--porcelain", "-b"], cwd)
    if status:
        lines = status.splitlines()
        # First line: ## branch...tracking [ahead N, behind M]
        if lines and lines[0].startswith("##"):
            header = lines[0]
            if "[" in header:
                bracket = header[header.index("[") + 1 : header.index("]")]
                for part in bracket.split(","):
                    part = part.strip()
                    if part.startswith("ahead"):
                        try:
                            info["ahead"] = int(part.split()[-1])
                        except ValueError:
                            pass
                    elif part.startswith("behind"):
                        try:
                            info["behind"] = int(part.split()[-1])
                        except ValueError:
                            pass

            # Count file statuses
            for line in lines[1:]:
                if len(line) >= 2:
                    idx, wt = line[0], line[1]
                    if line.startswith("??"):
                        info["untracked"] += 1
                    else:
                        if idx != " " and idx != "?":
                            info["staged"] += 1
                        if wt != " " and wt != "?":
                            info["modified"] += 1

    info["dirty"] = info["staged"] > 0 or info["modified"] > 0 or info["untracked"] > 0

    # Stash count
    stash = _run_git(["stash", "list"], cwd)
    if stash:
        info["stash_count"] = len(stash.splitlines())

    # Last commit message (first line)
    msg = _run_git(["log", "-1", "--format=%s"], cwd)
    if msg:
        info["last_commit_msg"] = msg[:80]  # Truncate for display

    return info


def get_git_info(cwd: str | None = None) -> Dict[str, Any]:
    """Get git info for a directory, with 10s cache.

    Returns a dict with: branch, dirty, ahead, behind, untracked,
    staged, modified, stash_count, last_commit_msg, is_repo.
    """
    if not cwd:
        cwd = os.getcwd()

    cache_file = _cache_path(cwd)

    # Check cache
    try:
        if cache_file.exists():
            stat = cache_file.stat()
            if time.time() - stat.st_mtime < CACHE_TTL_SECONDS:
                data = json.loads(cache_file.read_text())
                if isinstance(data, dict):
                    return data
    except (OSError, json.JSONDecodeError):
        pass

    # Compute fresh
    info = _compute_git_info(cwd)

    # Write cache (best-effort)
    try:
        cache_file.write_text(json.dumps(info))
    except OSError:
        pass

    return info
