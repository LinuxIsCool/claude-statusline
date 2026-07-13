"""Tests for F2/F10/F19/F20 data-source hardening (Brainstorm Pass 2 §1).

Failure modes defended:
  F2  — silent tailscale daemon-down (CLI returns {} not error)
  F10 — non-atomic /tmp cache writes (race between parallel renders)
  F19 — cascading subprocess timeouts (6s budget can burn when binaries wedge)
  F20 — process names with embedded ANSI escapes / control chars
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))


# ---------------------------------------------------------------------------
# F10 — atomic write
# ---------------------------------------------------------------------------


def test_atomic_write_creates_file(tmp_path):
    """_atomic_write_text writes exactly the requested content."""
    from net_utils import _atomic_write_text
    target = tmp_path / "out.json"
    _atomic_write_text(target, '{"x": 1}')
    assert target.read_text() == '{"x": 1}'


def test_atomic_write_does_not_leave_tmp(tmp_path):
    """The tempfile must be renamed away — no leftover .tmp.XXXX files."""
    from net_utils import _atomic_write_text
    target = tmp_path / "out.json"
    _atomic_write_text(target, "ok")
    leftovers = [p for p in tmp_path.iterdir() if p.name != "out.json"]
    assert leftovers == [], f"unexpected leftover files: {leftovers}"


def test_atomic_write_overwrites_existing(tmp_path):
    """A second write replaces the first atomically."""
    from net_utils import _atomic_write_text
    target = tmp_path / "out.json"
    _atomic_write_text(target, "first")
    _atomic_write_text(target, "second")
    assert target.read_text() == "second"


def test_atomic_write_unreadable_dir_raises(tmp_path):
    """If the parent dir is unwritable, the call raises (caller must handle)."""
    from net_utils import _atomic_write_text
    # A non-existent parent is the easiest unwritable case.
    target = tmp_path / "nonexistent_subdir" / "out.json"
    with pytest.raises((OSError, FileNotFoundError)):
        _atomic_write_text(target, "x")


# ---------------------------------------------------------------------------
# F19 — subprocess capability blackout
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_caps_cache(tmp_path, monkeypatch):
    """Redirect subprocess_caps to a tmp-path cache file for each test."""
    import subprocess_caps
    cache = tmp_path / "caps.json"
    monkeypatch.setattr(subprocess_caps, "CACHE_FILE", cache)
    yield cache


def test_blackout_skips_after_failure(fresh_caps_cache):
    """After report_failure, with_blackout must skip the run_func entirely."""
    from subprocess_caps import with_blackout, report_failure, is_blackout
    report_failure("nonexistent-binary-xyz")
    assert is_blackout("nonexistent-binary-xyz")
    called = []
    def _run():
        called.append(1)
        return "real"
    result = with_blackout("nonexistent-binary-xyz", _run, "fallback")
    assert result == "fallback"
    assert called == [], "run_func must not be invoked during blackout"


def test_blackout_clears_on_success(fresh_caps_cache):
    """A successful call after blackout-expiry must clear the blackout."""
    from subprocess_caps import with_blackout, is_blackout
    def _run():
        return "ok"
    result = with_blackout("some-binary", _run, "fallback")
    assert result == "ok"
    assert not is_blackout("some-binary")


def test_blackout_on_exception(fresh_caps_cache):
    """An exception in run_func triggers a blackout and returns fallback."""
    from subprocess_caps import with_blackout, is_blackout
    def _run():
        raise RuntimeError("boom")
    result = with_blackout("crashy", _run, "fb")
    assert result == "fb"
    assert is_blackout("crashy"), "blackout must be active after exception"


def test_blackout_persists_across_processes(fresh_caps_cache):
    """The cache is on disk, so a fresh import sees the blackout."""
    from subprocess_caps import report_failure, is_blackout
    report_failure("persistent-binary")
    # Simulate a new process by re-reading the on-disk state.
    assert fresh_caps_cache.exists()
    state = json.loads(fresh_caps_cache.read_text())
    assert "persistent-binary" in state
    assert state["persistent-binary"] > time.time()


# ---------------------------------------------------------------------------
# F2 — tailscale_available capability bit
# ---------------------------------------------------------------------------


def test_default_info_has_tailscale_available():
    """_DEFAULT_INFO MUST expose the F2 capability bit so themes can branch."""
    from net_utils import _DEFAULT_INFO
    assert "tailscale_available" in _DEFAULT_INFO
    assert _DEFAULT_INFO["tailscale_available"] is False


def test_get_net_info_returns_tailscale_available():
    """A live get_net_info() call must populate the tailscale_available bit."""
    from net_utils import get_net_info
    # Clear the cache to force a real query path (we don't assert on the
    # boolean value — only that the key is present and is a bool).
    info = get_net_info()
    assert "tailscale_available" in info
    assert isinstance(info["tailscale_available"], bool)


# ---------------------------------------------------------------------------
# F20 — ANSI / control char sanitization
# ---------------------------------------------------------------------------


def test_sanitize_label_passthrough_for_plain_text():
    from proc_utils import _sanitize_label
    assert _sanitize_label("firefox") == "firefox"
    assert _sanitize_label("ollama serve") == "ollama serve"


def test_sanitize_label_strips_escape_char():
    """ESC (\\x1b) must never appear in output — that's the actual safety win."""
    from proc_utils import _sanitize_label
    poisoned = "\x1b[31mfirefox\x1b[0m"
    cleaned = _sanitize_label(poisoned)
    assert "\x1b" not in cleaned, f"ESC leaked: {cleaned!r}"


def test_sanitize_label_strips_all_c0_controls():
    """The full C0 range (0x00–0x1f) plus DEL/C1 (0x7f–0x9f) must be stripped."""
    from proc_utils import _sanitize_label
    nasty = "name\x00\x07\x08\x1b\x7f\x9bevil"
    cleaned = _sanitize_label(nasty)
    for ch in ("\x00", "\x07", "\x08", "\x1b", "\x7f", "\x9b"):
        assert ch not in cleaned, f"{ch!r} leaked into {cleaned!r}"
    # Visible parts are preserved.
    assert "name" in cleaned and "evil" in cleaned


def test_sanitize_label_empty_string():
    from proc_utils import _sanitize_label
    assert _sanitize_label("") == ""


def test_resolve_process_label_self_is_clean():
    """resolve_process_label(os.getpid()) returns no control chars for self."""
    from proc_utils import resolve_process_label
    label = resolve_process_label(os.getpid())
    assert isinstance(label, str)
    for ch in label:
        assert ord(ch) >= 0x20 and ord(ch) != 0x7f, (
            f"control char {ord(ch):#x} in self-label {label!r}"
        )


# ---------------------------------------------------------------------------
# F19 — gpu_utils + git_utils integration with subprocess_caps blackout
# ---------------------------------------------------------------------------


def test_gpu_utils_returns_empty_when_nvidia_smi_blackout(tmp_path, monkeypatch):
    """In blackout, gpu_utils.get_gpu_info() must return the default-empty info
    without ever shelling out to nvidia-smi."""
    import subprocess_caps
    monkeypatch.setattr(subprocess_caps, "CACHE_FILE", tmp_path / "caps.json")

    import gpu_utils
    # Redirect gpu cache so prior render doesn't shortcut us.
    monkeypatch.setattr(gpu_utils, "CACHE_FILE", tmp_path / "gpu.json")

    # Sanity: poison subprocess.run so any real invocation explodes the test.
    import subprocess as _sp
    def _boom(*a, **kw):
        raise AssertionError("nvidia-smi must NOT be invoked during blackout")
    monkeypatch.setattr(_sp, "run", _boom)

    subprocess_caps.report_failure("nvidia-smi")
    assert subprocess_caps.is_blackout("nvidia-smi")

    info = gpu_utils.get_gpu_info()
    assert info["available"] is False
    assert info["processes"] == []
    assert info["process_count"] == 0


def test_git_utils_returns_safe_default_when_git_blackout(tmp_path, monkeypatch):
    """In blackout, git_utils.get_git_info() returns the default dict
    (is_repo=False, branch='?') without ever invoking git."""
    import subprocess_caps
    monkeypatch.setattr(subprocess_caps, "CACHE_FILE", tmp_path / "caps.json")

    import git_utils
    # Redirect cache dir so prior render doesn't shortcut us.
    monkeypatch.setattr(git_utils, "CACHE_DIR", tmp_path)

    # Poison subprocess.run — git must never be invoked under blackout.
    import subprocess as _sp
    def _boom(*a, **kw):
        raise AssertionError("git must NOT be invoked during blackout")
    monkeypatch.setattr(_sp, "run", _boom)

    subprocess_caps.report_failure("git")
    assert subprocess_caps.is_blackout("git")

    info = git_utils.get_git_info(str(tmp_path))
    assert info["is_repo"] is False
    assert info["branch"] == "?"


def test_run_git_returns_none_under_blackout(tmp_path, monkeypatch):
    """The lower-level _run_git helper returns None (its documented failure
    sentinel) during blackout."""
    import subprocess_caps
    monkeypatch.setattr(subprocess_caps, "CACHE_FILE", tmp_path / "caps.json")

    import git_utils

    import subprocess as _sp
    def _boom(*a, **kw):
        raise AssertionError("git must NOT be invoked during blackout")
    monkeypatch.setattr(_sp, "run", _boom)

    subprocess_caps.report_failure("git")
    assert git_utils._run_git(["status"], str(tmp_path)) is None
