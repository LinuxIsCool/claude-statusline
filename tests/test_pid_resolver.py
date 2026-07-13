"""Tests for pid_resolver — process-tree walk and session-keyed cache.

The walk is the core: given a starting pid, find the nearest ancestor
whose comm is "claude". The cache is the optimization: persist the
result keyed by session_id so we walk once per session.

Two test surfaces:

1. **Mocked /proc** — for deterministic walk behavior in CI. We patch
   the two `_read_proc_*` helpers to return values from a fake process
   tree. This exercises the walk algorithm without depending on the
   host's real process tree.

2. **Real /proc on the test host** — confirms the resolver actually
   finds *something* sensible when given os.getppid() on the actual
   machine. Skipped if /proc is absent.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import pytest

import pid_resolver


# ── Mocked process-tree fixtures ──────────────────────────────────────

def _install_fake_tree(monkeypatch, tree: dict[int, tuple[str, int]]) -> None:
    """Patch pid_resolver to read from a fake tree.

    Tree shape: {pid: (comm, ppid), ...}
    Missing pids → reads return None (simulating a dead process).
    """
    def fake_comm(pid: int):
        entry = tree.get(pid)
        return entry[0] if entry else None

    def fake_ppid(pid: int):
        entry = tree.get(pid)
        return entry[1] if entry else None

    monkeypatch.setattr(pid_resolver, "_read_proc_comm", fake_comm)
    monkeypatch.setattr(pid_resolver, "_read_proc_ppid", fake_ppid)


# ── Walk tests ────────────────────────────────────────────────────────

def test_walk_immediate_claude_parent(monkeypatch):
    """Most common case: getppid() IS claude → return it directly."""
    _install_fake_tree(monkeypatch, {
        9000: ("claude", 1),
    })
    assert pid_resolver._walk_to_claude(9000) == 9000


def test_walk_through_shell_to_claude(monkeypatch):
    """zsh → claude → ... — one hop walk."""
    _install_fake_tree(monkeypatch, {
        12345: ("zsh", 9000),
        9000: ("claude", 1),
    })
    assert pid_resolver._walk_to_claude(12345) == 9000


def test_walk_through_uv_hook_to_claude(monkeypatch):
    """uv → hook-runner → ... → claude — multiple hops."""
    _install_fake_tree(monkeypatch, {
        22222: ("uv", 22221),
        22221: ("status.py", 22220),
        22220: ("python3", 9000),
        9000: ("claude", 1),
    })
    assert pid_resolver._walk_to_claude(22222) == 9000


def test_walk_accepts_claude_code_variant(monkeypatch):
    """Some installs name the binary `claude-code` rather than `claude`.
    The resolver should accept either."""
    _install_fake_tree(monkeypatch, {
        12345: ("zsh", 9001),
        9001: ("claude-code", 1),
    })
    assert pid_resolver._walk_to_claude(12345) == 9001


def test_walk_hits_init_without_finding_claude(monkeypatch):
    """Process tree that never contains claude (e.g., a cron job) →
    None, caller falls back to start_pid."""
    _install_fake_tree(monkeypatch, {
        100: ("cron", 99),
        99: ("systemd", 1),
    })
    assert pid_resolver._walk_to_claude(100) is None


def test_walk_handles_dead_process_in_chain(monkeypatch):
    """If a /proc read returns None mid-walk, the walk aborts (the
    race-tolerant behavior). Caller falls back to start_pid."""
    _install_fake_tree(monkeypatch, {
        500: ("python", 499),
        # 499 is a "dead" process — no entry in tree, reads return None
    })
    assert pid_resolver._walk_to_claude(500) is None


def test_walk_bounded_by_max_depth(monkeypatch):
    """Defensive: a pathologically deep tree should terminate within
    _MAX_WALK_DEPTH iterations rather than loop forever."""
    # Build a 200-deep linear chain ending in (not) claude
    tree = {i: (f"proc{i}", i - 1) for i in range(2, 200)}
    tree[1] = ("init", 0)
    _install_fake_tree(monkeypatch, tree)
    # Should not hang; should return None (claude not in the chain)
    assert pid_resolver._walk_to_claude(199) is None


def test_walk_handles_pid_zero_or_negative(monkeypatch):
    """If start_pid <= 1, return None immediately (don't try to read
    /proc/0 or /proc/1 as a claude candidate)."""
    _install_fake_tree(monkeypatch, {})
    assert pid_resolver._walk_to_claude(1) is None
    assert pid_resolver._walk_to_claude(0) is None
    assert pid_resolver._walk_to_claude(-5) is None


# ── resolve() integration tests ───────────────────────────────────────

def test_resolve_returns_walked_pid_when_no_session_id(monkeypatch):
    """No session_id → no cache → fresh walk every call."""
    _install_fake_tree(monkeypatch, {
        12345: ("zsh", 9000),
        9000: ("claude", 1),
    })
    assert pid_resolver.resolve(12345) == 9000


def test_resolve_falls_back_to_start_pid_when_no_claude(monkeypatch):
    """Walk fails → return start_pid (preserves v0.5.2 behavior)."""
    _install_fake_tree(monkeypatch, {
        100: ("cron", 99),
        99: ("systemd", 1),
    })
    assert pid_resolver.resolve(100) == 100


def test_resolve_caches_per_session(tmp_path, monkeypatch):
    """First call walks and writes cache. Second call with same
    session_id reads cache (and still validates liveness via comm)."""
    monkeypatch.setattr(pid_resolver, "CACHE_DIR", tmp_path)

    tree = {
        12345: ("zsh", 9000),
        9000: ("claude", 1),
    }
    _install_fake_tree(monkeypatch, tree)

    sid = "abc12345-test"
    # First call — fresh walk + cache write
    assert pid_resolver.resolve(12345, session_id=sid) == 9000
    cache_file = pid_resolver._cache_path(sid)
    assert cache_file.exists()
    data = json.loads(cache_file.read_text())
    assert data["pid"] == 9000
    assert data["session_id"] == sid

    # Second call — cache hit (we'd return even if start_pid changes,
    # as long as the cached pid is still alive in the fake tree)
    assert pid_resolver.resolve(99999, session_id=sid) == 9000


def test_resolve_invalidates_cache_when_pid_died(tmp_path, monkeypatch):
    """If the cached pid no longer maps to a claude comm (e.g., session
    died and the OS reused that pid), the resolver does a fresh walk
    instead of trusting stale data."""
    monkeypatch.setattr(pid_resolver, "CACHE_DIR", tmp_path)

    sid = "dead-session-test"
    # Pre-seed a cache pointing at pid 9000
    cache_file = pid_resolver._cache_path(sid)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({"pid": 9000, "session_id": sid}))

    # Tree now has pid 9000 as NOT claude (the OS recycled it for
    # something else after the original session died).
    _install_fake_tree(monkeypatch, {
        12345: ("zsh", 7777),
        9000: ("firefox", 1),  # pid reused for an unrelated process
        7777: ("claude", 1),
    })

    # Resolver should detect the cache is stale (comm mismatch) and
    # walk fresh from start_pid=12345 → claude=7777.
    assert pid_resolver.resolve(12345, session_id=sid) == 7777


def test_resolve_recovers_from_corrupted_cache(tmp_path, monkeypatch):
    """A truncated / invalid JSON cache must not crash the resolver."""
    monkeypatch.setattr(pid_resolver, "CACHE_DIR", tmp_path)

    sid = "corrupt-test"
    cache_file = pid_resolver._cache_path(sid)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text('{"pid":99999,"sess')  # truncated JSON

    _install_fake_tree(monkeypatch, {
        12345: ("zsh", 8888),
        8888: ("claude", 1),
    })

    # Should fall through to fresh walk and find claude at 8888.
    assert pid_resolver.resolve(12345, session_id=sid) == 8888


def test_resolve_atomic_under_concurrent_calls(tmp_path, monkeypatch):
    """Multiple statusline processes calling resolve() with the same
    session_id at the same time must not corrupt the cache file. We
    reuse the same atomic-write pattern as persona_utils."""
    monkeypatch.setattr(pid_resolver, "CACHE_DIR", tmp_path)

    _install_fake_tree(monkeypatch, {
        12345: ("zsh", 9000),
        9000: ("claude", 1),
    })

    sid = "concurrent-test"
    errors: list[str] = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        for _ in range(15):
            try:
                pid = pid_resolver.resolve(12345, session_id=sid)
                assert pid == 9000
                # Validate cache is parseable on every iteration
                cf = pid_resolver._cache_path(sid)
                if cf.exists():
                    json.loads(cf.read_text())
            except json.JSONDecodeError as e:
                errors.append(f"truncated cache: {e}")
            except Exception as e:
                errors.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join(timeout=10)
    assert not errors, f"Concurrent cache writes produced errors: {errors[:3]}"


# ── Real-/proc smoke test ────────────────────────────────────────────

def test_resolve_against_real_proc():
    """End-to-end on the test host. We call resolve(getppid()) and
    expect either:
      - A real pid (resolver found a claude ancestor), or
      - getppid() itself (no claude in ancestry — test runner outside Claude)

    Either way, the returned pid must exist as a valid /proc entry.
    """
    if not Path("/proc/self/comm").exists():
        pytest.skip("/proc not available — non-Linux test host")
    ppid = os.getppid()
    result = pid_resolver.resolve(ppid)
    assert isinstance(result, int)
    assert result > 0
    # The returned pid must be alive (we just read /proc for it)
    assert Path(f"/proc/{result}").exists(), (
        f"resolver returned non-existent pid {result}"
    )


def test_session_id_safe_against_path_traversal(tmp_path, monkeypatch):
    """Defense: a session_id containing slashes / dots must not allow
    the cache to escape CACHE_DIR. The cache_path sanitizer should
    strip everything except alphanumerics and hyphens."""
    monkeypatch.setattr(pid_resolver, "CACHE_DIR", tmp_path)

    # Try a path-traversal attempt
    sid = "../../../etc/passwd"
    cache_file = pid_resolver._cache_path(sid)
    # Must stay under tmp_path
    assert tmp_path in cache_file.parents or cache_file.parent == tmp_path
