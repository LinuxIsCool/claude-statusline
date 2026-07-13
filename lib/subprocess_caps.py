"""Subprocess capability cache with blackout-after-timeout pattern.

When a binary times out or errors, record it as unavailable for BLACKOUT_SECONDS.
Subsequent callers skip the subprocess invocation, returning the configured
fallback value immediately.

Use case: prevent a wedged `tailscale status --json` from costing 2s on every
statusline render for the duration of its wedged state. With six potential
subprocess calls per render (tailscale, nmcli, git, nvidia-smi, ...), one
wedged binary alone can burn the entire hook deadline.

Defense pattern (per Brainstorm Pass 2 §1 F19): "capability-cache 'tailscale:
slow' for 60s if it ever times out, skip it entirely during that window."
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

CACHE_FILE = Path("/tmp/statusline-subprocess-caps.json")
BLACKOUT_SECONDS = 60


def _load_state() -> dict[str, float]:
    """Load {binary_name: blackout_until_ts} dict. Tolerates absent/corrupt cache."""
    try:
        return json.loads(CACHE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict[str, float]) -> None:
    """Persist state via atomic tempfile + rename (race-safe across renders)."""
    try:
        fd, tmp = tempfile.mkstemp(prefix=CACHE_FILE.name + ".", dir=str(CACHE_FILE.parent))
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f)
            os.rename(tmp, CACHE_FILE)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError:
        pass


def is_blackout(binary: str) -> bool:
    """True if binary is currently in blackout (skip subprocess invocation)."""
    state = _load_state()
    until = state.get(binary, 0)
    return time.time() < until


def report_failure(binary: str) -> None:
    """Mark binary as failed; blackout for BLACKOUT_SECONDS."""
    state = _load_state()
    state[binary] = time.time() + BLACKOUT_SECONDS
    _save_state(state)


def report_success(binary: str) -> None:
    """Clear blackout for binary (if any)."""
    state = _load_state()
    if binary in state:
        del state[binary]
        _save_state(state)


def with_blackout(binary: str, run_func: Callable[[], Any], fallback: Any) -> Any:
    """Wrap a subprocess call with the blackout pattern.

    Returns the result of run_func() if successful, OR `fallback` if:
    - The binary is currently in blackout (skips invocation entirely)
    - The call raises any exception (records failure, returns fallback)

    The caller is responsible for ensuring run_func() itself has an
    appropriate timeout — the blackout pattern AMPLIFIES the value of that
    timeout (one slow call poisons the next 60s) but does not replace it.
    """
    if is_blackout(binary):
        return fallback
    try:
        result = run_func()
        report_success(binary)
        return result
    except Exception:
        report_failure(binary)
        return fallback
