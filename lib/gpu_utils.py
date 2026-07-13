"""GPU metrics via nvidia-smi with filesystem caching for claude-statusline.

Uses nvidia-smi --query-gpu CSV mode for clean, parseable output.
Cache to /tmp with 3-second TTL — GPU stats change fast.
Never crash — returns safe defaults on any failure.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict

# subprocess_caps lives in the same lib/ directory.
sys.path.insert(0, str(Path(__file__).parent))
from subprocess_caps import with_blackout  # noqa: E402

CACHE_TTL_SECONDS = 3
CACHE_FILE = Path("/tmp/statusline-gpu.json")

# Sentinel returned by with_blackout when nvidia-smi is in blackout (or the
# call itself raised). Distinct object identity so we can branch on `is`.
_BLACKOUT = object()

# Fields to query and their nvidia-smi names
_GPU_FIELDS = [
    "name",
    "utilization.gpu",       # % GPU core usage
    "utilization.memory",    # % memory controller usage
    "memory.used",           # MiB used
    "memory.total",          # MiB total
    "temperature.gpu",       # °C
    "power.draw",            # W
    "power.limit",           # W
    "fan.speed",             # %
    "clocks.current.graphics",  # MHz
    "clocks.current.memory",    # MHz
]

_DEFAULT_INFO: Dict[str, Any] = {
    "available": False,
    "name": "?",
    "gpu_util": 0,
    "mem_util": 0,
    "mem_used_mib": 0,
    "mem_total_mib": 0,
    "temp_c": 0,
    "power_w": 0.0,
    "power_limit_w": 0.0,
    "fan_pct": 0,
    "clock_gpu_mhz": 0,
    "clock_mem_mhz": 0,
    "processes": [],
    "process_count": 0,
}


def _parse_float(s: str, default: float = 0.0) -> float:
    """Parse a float from nvidia-smi output, handling [N/A] and whitespace."""
    v = s.strip()
    if not v or v == "[N/A]" or v == "N/A":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _parse_int(s: str, default: int = 0) -> int:
    """Parse an int from nvidia-smi output."""
    return int(_parse_float(s, float(default)))


def _compact_gpu_name(raw: str) -> str:
    """Compact an nvidia-smi GPU name for the statusline's fixed-width name cell.

    Drops marketing/form-factor noise that pushes the useful model past the
    cell width, e.g.:
      "NVIDIA GeForce RTX 4070"            -> "NVIDIA RTX 4070"
      "NVIDIA GeForce RTX 5080 Laptop GPU" -> "NVIDIA RTX 5080"
    Order matters: strip the longer " Laptop GPU" before a bare " Laptop".
    """
    name = raw.strip()
    for noise in (" GeForce", " Quadro", " Tesla", " Laptop GPU", " Laptop"):
        name = name.replace(noise, "")
    name = name.replace("(R)", "").replace("(TM)", "")
    return " ".join(name.split())  # collapse any double-spaces


def _query_gpu() -> Dict[str, Any]:
    """Query nvidia-smi for GPU metrics + running processes."""
    info = dict(_DEFAULT_INFO)

    # GPU metrics (single call, CSV, no units)
    # Guarded by subprocess_caps.with_blackout so a wedged nvidia-smi only
    # costs us the first 2s timeout; the next 60s of renders skip the call.
    def _query_gpu_metrics():
        r = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=" + ",".join(_GPU_FIELDS),
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2.0,
        )
        if r.returncode != 0:
            raise subprocess.CalledProcessError(r.returncode, "nvidia-smi")
        return r

    result = with_blackout("nvidia-smi", _query_gpu_metrics, _BLACKOUT)
    if result is _BLACKOUT:
        return info
    try:
        # maxsplit so commas in GPU name don't shift field positions
        # (e.g. "NVIDIA GeForce RTX 4070, Laptop GPU" would break naive split)
        parts = result.stdout.strip().split(",", maxsplit=len(_GPU_FIELDS) - 1)
        if len(parts) < len(_GPU_FIELDS):
            return info

        info["available"] = True
        info["name"] = _compact_gpu_name(parts[0])
        info["gpu_util"] = _parse_int(parts[1])
        info["mem_util"] = _parse_int(parts[2])
        info["mem_used_mib"] = _parse_int(parts[3])
        info["mem_total_mib"] = _parse_int(parts[4])
        info["temp_c"] = _parse_int(parts[5])
        info["power_w"] = _parse_float(parts[6])
        info["power_limit_w"] = _parse_float(parts[7])
        info["fan_pct"] = _parse_int(parts[8])
        info["clock_gpu_mhz"] = _parse_int(parts[9])
        info["clock_mem_mhz"] = _parse_int(parts[10])
    except (ValueError, IndexError, AttributeError):
        return info

    # Running processes — TWO sources merged:
    #   1. --query-compute-apps: CUDA compute apps with exact VRAM in MiB
    #   2. nvidia-smi pmon -c 1: ALL processes touching the GPU (compute + graphics)
    #      so we don't lose kwin_wayland, firefox, OBS, browser tabs, etc.
    pmon_data: Dict[int, Dict[str, Any]] = {}

    def _query_pmon():
        r = subprocess.run(
            ["nvidia-smi", "pmon", "-c", "1"],
            capture_output=True, text=True, timeout=2.0,
        )
        if r.returncode != 0:
            raise subprocess.CalledProcessError(r.returncode, "nvidia-smi")
        return r

    pmon = with_blackout("nvidia-smi", _query_pmon, _BLACKOUT)
    if pmon is not _BLACKOUT:
        try:
            for line in pmon.stdout.splitlines():
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.split()
                # gpu_idx pid type sm mem enc dec jpg ofa command
                if len(parts) < 10:
                    continue
                try:
                    pid = int(parts[1])
                except ValueError:
                    continue
                mem_str = parts[4]
                try:
                    mem_pct = float(mem_str) if mem_str not in ("-", "") else 0.0
                except ValueError:
                    mem_pct = 0.0
                pmon_data[pid] = {
                    "type": parts[2],
                    "mem_pct": mem_pct,
                    "command": parts[-1],
                }
        except (ValueError, IndexError, AttributeError):
            pass  # parse failure — fall back to compute-apps only

    procs: list = []
    compute_apps_ran = False

    def _query_compute_apps():
        r = subprocess.run(
            ["nvidia-smi",
             "--query-compute-apps=pid,used_gpu_memory,name",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2.0,
        )
        if r.returncode != 0:
            raise subprocess.CalledProcessError(r.returncode, "nvidia-smi")
        return r

    result = with_blackout("nvidia-smi", _query_compute_apps, _BLACKOUT)
    if result is _BLACKOUT:
        # compute-apps unavailable; still let the pmon-graphics fallback run.
        compute_apps_ran = False
    else:
        compute_apps_ran = True
    try:
        if compute_apps_ran and result.stdout.strip():
            for line in result.stdout.strip().splitlines():
                parts = line.split(",")
                if len(parts) >= 3:
                    pid_str = parts[0].strip()
                    mem_mib = _parse_int(parts[1])
                    # We ignore nvidia-smi's own name field (often just 'python3').
                    # proc_utils.resolve_process_label gives high-signal names like
                    # 'whisperx', 'ollama', 'comfyui' by inspecting /proc/<pid>/cmdline.
                    try:
                        pid_int = int(pid_str)
                    except ValueError:
                        pid_int = 0
                    procs.append({
                        "pid": pid_str,
                        "pid_int": pid_int,
                        "mem_mib": mem_mib,
                        "name": "?",
                    })

        # NOTE: We deliberately do NOT merge pmon's graphics processes into the
        # procs list with synthetic VRAM. nvidia-smi pmon's `mem` column is
        # *memory bandwidth utilization %*, NOT VRAM allocation %. Multiplying
        # it by total VRAM produces nonsense (kwin_wayland at 11% bandwidth →
        # "1.3GB" which has nothing to do with its actual VRAM footprint).
        # Only CUDA compute apps have per-process VRAM exposed by the driver.
        # Graphics workloads (compositor, browsers, OBS) live in the "+other"
        # gap, computed as total_used_vram − sum(compute_apps_vram).
        # We DO consult pmon_data when there are zero compute apps so the
        # procs row isn't entirely em-dashes (see below).

        # Re-label compute-app processes via proc_utils (best-effort).
        if procs:
            try:
                from proc_utils import resolve_process_label  # type: ignore[import-not-found]
                for p in procs:
                    if p["pid_int"] > 0:
                        p["name"] = resolve_process_label(p["pid_int"])
            except Exception:
                # Fall back to nvidia-smi's name field if proc_utils unavailable.
                for p, line in zip(procs, result.stdout.strip().splitlines()):
                    parts = line.split(",")
                    if len(parts) >= 3:
                        raw_name = parts[2].strip()
                        short = raw_name.rsplit("/", 1)[-1] if "/" in raw_name else raw_name
                        p["name"] = short.split()[0] if " " in short else short

        # Sort by VRAM descending
        procs.sort(key=lambda p: -p["mem_mib"])

        # When there are NO compute apps but pmon reports graphics activity,
        # surface a single graphics-app indicator so the procs row isn't
        # entirely em-dashes when the user is just running desktop + browser.
        # Tagged "(graphics)" so the user knows VRAM is via +other accounting.
        if not procs and pmon_data:
            top_pid, top_data = max(
                pmon_data.items(),
                key=lambda kv: kv[1].get("mem_pct", 0.0),
            )
            gname = top_data.get("command", "?")
            try:
                from proc_utils import resolve_process_label  # type: ignore[import-not-found]
                gname = resolve_process_label(top_pid) or gname
            except Exception:
                pass
            procs.append({
                "pid": str(top_pid),
                "pid_int": top_pid,
                "mem_mib": 0,
                "name": f"{gname} (graphics)",
            })

        # 'Other VRAM' = total_used - sum(known compute proc VRAM).
        # When the only proc is a graphics-marker (mem_mib=0), other_vram_mib
        # equals total_used → user sees graphics + driver footprint as
        # honest gap-accounting.
        mem_used = info.get("mem_used_mib", 0)
        sum_known = sum(p["mem_mib"] for p in procs)
        info["other_vram_mib"] = max(0, mem_used - sum_known)

        info["processes"] = procs
        info["process_count"] = len(procs)
    except (ValueError, IndexError, AttributeError):
        pass  # Processes are best-effort

    return info


def get_gpu_info() -> Dict[str, Any]:
    """Get GPU info with 3s cache. Returns dict with all metrics."""
    # Check cache
    try:
        if CACHE_FILE.exists():
            stat = CACHE_FILE.stat()
            if time.time() - stat.st_mtime < CACHE_TTL_SECONDS:
                data = json.loads(CACHE_FILE.read_text())
                if isinstance(data, dict):
                    return data
    except (OSError, json.JSONDecodeError):
        pass

    # Compute fresh
    info = _query_gpu()

    # Write cache (best-effort)
    try:
        CACHE_FILE.write_text(json.dumps(info))
    except OSError:
        pass

    return info
