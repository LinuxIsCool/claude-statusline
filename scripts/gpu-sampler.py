#!/usr/bin/env python3
"""claude-statusline GPU sampler — keeps the GPU cache warm OFF the render path.

Problem: on power-gating laptop GPUs (e.g. RTX 5080 Laptop), the first
nvidia-smi call after the GPU deep-idles pays ~2.5s of NVML/driver cold-init,
independent of which fields are queried. The statusline renders every ~300ms
and must never block that long, so its own query uses a conservative 2.0s
timeout — which the cold call exceeds, tripping a 60s blackout and leaving the
GPU section dark.

Solution: a tiny background daemon that samples nvidia-smi on its own schedule
(off the render path, with a generous warm-up) and writes the very cache file
the statusline already reads (`gpu_utils.CACHE_FILE`, 3s TTL). While this runs,
`get_gpu_info()` always finds a fresh cache and NEVER calls nvidia-smi itself —
so the render never blocks, and the GPU section is always populated. Frequent
sampling also keeps the GPU/driver warm, so steady-state samples are ~0.02s.

Reuses `gpu_utils._query_gpu()` verbatim so the cache schema can never drift
from what the renderer expects. Stdlib only; no external deps.

Tradeoff: sampling keeps the dGPU from entering its deepest runtime-suspend
(the inherent cost of live GPU monitoring). Disable on battery with:
    systemctl --user stop statusline-gpu-sampler.service
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Import the plugin's own GPU library so parsing + cache path stay identical.
_LIB = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(_LIB))
import gpu_utils  # noqa: E402
import subprocess_caps  # noqa: E402

INTERVAL_SECONDS = 2.0        # < gpu_utils.CACHE_TTL_SECONDS (3s) so cache never goes stale
WARMUP_TIMEOUT_SECONDS = 8.0  # generous: absorbs the ~2.5s cold NVML init off the render path

_running = True


def _stop(signum, frame):  # noqa: ARG001
    global _running
    _running = False


def _warm_up() -> None:
    """Wake NVML/driver with a generous timeout so the subsequent _query_gpu()
    (which uses the plugin's conservative 2s timeout) runs warm and succeeds."""
    try:
        subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=WARMUP_TIMEOUT_SECONDS,
        )
    except Exception:
        pass  # if this fails, _query_gpu() will record unavailable — graceful


def _write_cache_atomic(info: dict) -> None:
    """Atomic write so the renderer never reads a half-written cache file."""
    cache = gpu_utils.CACHE_FILE
    try:
        fd, tmp = tempfile.mkstemp(dir=str(cache.parent), prefix=".gpu-", suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(info, f)
        os.replace(tmp, cache)
    except OSError:
        pass


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    while _running:
        start = time.monotonic()
        _warm_up()
        # Clear any prior blackout so _query_gpu() actually shells out (now warm).
        subprocess_caps.report_success("nvidia-smi")
        info = gpu_utils._query_gpu()
        _write_cache_atomic(info)
        # Sleep the remainder of the interval (guard against negative on cold cycles).
        elapsed = time.monotonic() - start
        time.sleep(max(0.1, INTERVAL_SECONDS - elapsed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
