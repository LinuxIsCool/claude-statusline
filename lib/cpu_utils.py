"""CPU + RAM metrics for claude-statusline.

Provides:
  - CPU package temperature (°C)   — hwmon-first, thermal-db fallback
  - CPU usage percentage           — /proc/stat delta across cache reads
  - RAM usage percentage + amounts — /proc/meminfo (MemTotal vs MemAvailable)

Cache to /tmp with 3-second TTL — same pattern as gpu_utils.
A separate prev-snapshot file holds the last /proc/stat reading so we can
compute the busy-vs-idle delta without sleeping.

Pure stdlib only (no psutil dependency). Never crash — returns safe defaults on any failure.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CACHE_TTL_SECONDS = 3
CACHE_FILE = Path("/tmp/statusline-cpu.json")
CPU_PREV_FILE = Path("/tmp/statusline-cpu-prev.json")            # /proc/stat snapshot
CPU_RAPL_PREV_FILE = Path("/tmp/statusline-cpu-rapl-prev.json")  # RAPL energy_uj snapshot
THERMAL_DB = Path.home() / ".claude/local/thermal/thermal.db"
HWMON_ROOT = Path("/sys/class/hwmon")
PROC_STAT = Path("/proc/stat")
PROC_MEMINFO = Path("/proc/meminfo")
PROC_ROOT = Path("/proc")
RAPL_ROOT = Path("/sys/class/powercap/intel-rapl:0")
CPUFREQ_ROOT = Path("/sys/devices/system/cpu")

# Page size for converting statm pages → bytes. Falls back to 4096 if sysconf missing.
try:
    _PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")
except (AttributeError, ValueError, OSError):
    _PAGE_SIZE = 4096

# Cached once (CPU model name doesn't change at runtime).
_CPU_NAME_CACHED: Optional[str] = None

# Common LPC/SuperIO chips that expose fan*_input on hwmon. Best-effort.
_FAN_CHIPS = {
    "nct6798", "nct6797", "nct6796", "nct6795", "nct6793", "nct6791",
    "it8772", "it8728", "it8721",
    "thinkpad", "ideapad_acpi", "lenovo_legion",
    "asus-nb-wmi", "dell_smm",
}

_DEFAULT_INFO: Dict[str, Any] = {
    "available": False,
    "name": "CPU",
    "source": None,          # "thermal-db" | "hwmon" | None
    "chip": "?",
    "sensor": "?",
    "temp_c": 0,             # package / Tctl °C as int
    "high_c": 0,             # high threshold °C
    "critical_c": 0,         # critical threshold °C
    "age_seconds": -1,       # only meaningful for thermal-db source
    "cpu_pct": 0.0,          # CPU usage % since previous statusline call
    "ram_pct": 0.0,          # RAM usage %
    "ram_used_mib": 0,
    "ram_total_mib": 0,
    "clock_mhz": 0,          # average current core frequency
    "power_w": 0.0,          # current package power draw (0 if RAPL gated)
    "power_limit_w": 0.0,    # RAPL constraint_0_max_power_uw / PL1
    "power_available": False,
    "fan_pct": 0,            # 0 if no fan sensor exposed
    "fan_available": False,
    "processes": [],         # top N by RSS, [{name, mem_mib}]
}


def _from_thermal_db() -> Optional[Dict[str, Any]]:
    if not THERMAL_DB.exists():
        return None
    try:
        with sqlite3.connect(f"file:{THERMAL_DB}?mode=ro", uri=True, timeout=0.5) as conn:
            conn.row_factory = sqlite3.Row
            # Prefer Intel coretemp Package id 0; fall back to any 'Package' or 'Tctl'.
            for sensor_pattern in ("Package id 0", "Package", "Tctl", "Tdie"):
                row = conn.execute(
                    "SELECT chip, sensor, current, high, critical, ts "
                    "FROM latest "
                    "WHERE sensor = ? "
                    "ORDER BY chip LIMIT 1",
                    (sensor_pattern,),
                ).fetchone()
                if row:
                    age = -1
                    try:
                        # ts is ISO-8601 UTC like '2026-05-31T17:30:45+00:00'
                        from datetime import datetime, timezone
                        ts = datetime.fromisoformat(row["ts"])
                        age = int((datetime.now(timezone.utc) - ts).total_seconds())
                    except Exception:
                        pass
                    return {
                        "available": True,
                        "source": "thermal-db",
                        "chip": row["chip"],
                        "sensor": row["sensor"],
                        "temp_c": int(round(row["current"])),
                        "high_c": int(row["high"] or 0),
                        "critical_c": int(row["critical"] or 0),
                        "age_seconds": age,
                    }
    except sqlite3.Error:
        return None
    return None


def _from_hwmon() -> Optional[Dict[str, Any]]:
    """Scan /sys/class/hwmon for coretemp (Intel) or k10temp (AMD)."""
    if not HWMON_ROOT.exists():
        return None
    candidates = []
    for hwmon in sorted(HWMON_ROOT.glob("hwmon*")):
        name_file = hwmon / "name"
        if not name_file.exists():
            continue
        try:
            chip = name_file.read_text().strip()
        except OSError:
            continue
        if chip in ("coretemp", "k10temp", "zenpower"):
            candidates.append((chip, hwmon))

    if not candidates:
        return None

    chip, hwmon = candidates[0]
    # For coretemp: temp1 is Package id 0. For k10temp: temp1 is Tctl.
    temp_file = hwmon / "temp1_input"
    if not temp_file.exists():
        return None

    try:
        millideg = int(temp_file.read_text().strip())
    except (OSError, ValueError):
        return None

    high = 0
    crit = 0
    label = "Package id 0" if chip == "coretemp" else "Tctl"
    for thr_name, var in (("temp1_max", "high"), ("temp1_crit", "critical")):
        thr_file = hwmon / thr_name
        if thr_file.exists():
            try:
                val = int(thr_file.read_text().strip()) // 1000
                if var == "high":
                    high = val
                else:
                    crit = val
            except (OSError, ValueError):
                pass
    label_file = hwmon / "temp1_label"
    if label_file.exists():
        try:
            label = label_file.read_text().strip()
        except OSError:
            pass

    return {
        "available": True,
        "source": "hwmon",
        "chip": chip,
        "sensor": label,
        "temp_c": millideg // 1000,
        "high_c": high,
        "critical_c": crit,
        "age_seconds": 0,
    }


def _read_proc_stat() -> Optional[Tuple[int, int]]:
    """Return (total_jiffies, idle_jiffies) from /proc/stat's first 'cpu' line.

    The aggregated cpu line has 10 fields after the label:
        user nice system idle iowait irq softirq steal guest guest_nice
    idle time = idle + iowait (per kernel doc convention).
    """
    try:
        with PROC_STAT.open() as f:
            first = f.readline()
    except OSError:
        return None
    if not first.startswith("cpu "):
        return None
    parts = first.split()
    try:
        vals = [int(x) for x in parts[1:]]
    except ValueError:
        return None
    if len(vals) < 4:
        return None
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
    total = sum(vals)
    return total, idle


def _cpu_usage_pct() -> float:
    """Compute CPU% over the delta since the last snapshot file. Returns 0 on first call."""
    sample = _read_proc_stat()
    if sample is None:
        return 0.0
    total, idle = sample

    prev: Optional[Dict[str, int]] = None
    if CPU_PREV_FILE.exists():
        try:
            prev = json.loads(CPU_PREV_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            prev = None

    # Always write the new snapshot for the next call.
    try:
        CPU_PREV_FILE.write_text(json.dumps({"total": total, "idle": idle, "ts": time.time()}))
    except OSError:
        pass

    if not prev:
        return 0.0
    dt = total - int(prev.get("total", 0))
    di = idle - int(prev.get("idle", 0))
    if dt <= 0:
        return 0.0
    busy_pct = (1.0 - (di / dt)) * 100.0
    # Clamp to sensible range
    return max(0.0, min(100.0, round(busy_pct, 1)))


def _ram_usage() -> Tuple[float, int, int]:
    """Read /proc/meminfo. Return (pct_used, used_mib, total_mib)."""
    try:
        text = PROC_MEMINFO.read_text()
    except OSError:
        return 0.0, 0, 0
    info: Dict[str, int] = {}
    for line in text.splitlines():
        # Lines look like:  MemTotal:       32868792 kB
        parts = line.split(":")
        if len(parts) != 2:
            continue
        key = parts[0].strip()
        val_parts = parts[1].split()
        if not val_parts:
            continue
        try:
            info[key] = int(val_parts[0])  # value is in kB
        except ValueError:
            continue
        if len(info) >= 6:  # we only need a handful — short-circuit
            if "MemTotal" in info and "MemAvailable" in info:
                break

    total_kb = info.get("MemTotal", 0)
    avail_kb = info.get("MemAvailable", 0)
    if total_kb <= 0 or avail_kb <= 0:
        return 0.0, 0, 0
    used_kb = total_kb - avail_kb
    pct = round(used_kb / total_kb * 100.0, 1)
    return pct, used_kb // 1024, total_kb // 1024


def _cpu_name() -> str:
    """Parse a short CPU model name with vendor prefix from /proc/cpuinfo.

    Returns 'Intel i7-13700F' / 'AMD Ryzen 7 7700X' / etc — vendor prefix
    matches the GPU naming convention ('NVIDIA RTX 4070', 'AMD RX 7900 XT').
    Cached once per process.
    """
    global _CPU_NAME_CACHED
    if _CPU_NAME_CACHED is not None:
        return _CPU_NAME_CACHED

    name = "CPU"
    raw_model = ""
    vendor_id = ""
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name") and not raw_model:
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        raw_model = parts[1].strip()
                elif line.startswith("vendor_id") and not vendor_id:
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        vendor_id = parts[1].strip()
                if raw_model and vendor_id:
                    break
    except OSError:
        pass

    # Map vendor_id → display prefix (matches GPU vendor naming pattern).
    if vendor_id == "GenuineIntel":
        vendor = "Intel"
    elif vendor_id == "AuthenticAMD":
        vendor = "AMD"
    else:
        vendor = vendor_id or ""

    if raw_model:
        # Strip noise marks and frequency trailer.
        clean = raw_model.replace("(R)", "").replace("(TM)", "")
        clean = clean.split(" @ ")[0].strip()
        tokens = clean.split()

        # 1) Intel: find the iN-XXXXX token.
        import re
        intel_match = re.search(r"\bi[3579]-\d{4,5}[A-Z]*\b", clean)
        if intel_match:
            model = intel_match.group(0)
        else:
            # 2) AMD: 'Ryzen 7 7700X', 'EPYC 7763', 'Threadripper 7980X', etc.
            for i, t in enumerate(tokens):
                if t in ("Ryzen", "EPYC", "Threadripper", "Xeon"):
                    model = " ".join(tokens[i : i + 3]).rstrip(",")
                    break
            else:
                # 3) Last-resort: drop boilerplate prefixes from the marketing string.
                for prefix in (
                    "13th Gen ", "12th Gen ", "11th Gen ", "10th Gen ",
                    "Intel Core ", "AMD Ryzen ", "Intel ", "AMD ",
                ):
                    if clean.startswith(prefix):
                        clean = clean[len(prefix):]
                model = clean
        name = f"{vendor} {model}".strip() if vendor else model

    _CPU_NAME_CACHED = name
    return name


def _cpu_clock_mhz() -> int:
    """Average current frequency across all online cores (MHz). 0 if unreadable."""
    freqs: List[int] = []
    try:
        for cpu_dir in CPUFREQ_ROOT.glob("cpu[0-9]*"):
            f = cpu_dir / "cpufreq" / "scaling_cur_freq"
            if not f.exists():
                continue
            try:
                freqs.append(int(f.read_text().strip()))  # kHz
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    if freqs:
        return int(round(sum(freqs) / len(freqs) / 1000))  # kHz → MHz
    # /proc/cpuinfo fallback
    fallback: List[float] = []
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("cpu MHz"):
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        try:
                            fallback.append(float(parts[1].strip()))
                        except ValueError:
                            continue
    except OSError:
        pass
    return int(round(sum(fallback) / len(fallback))) if fallback else 0


def _cpu_power() -> Tuple[float, float, bool]:
    """Return (current_w, limit_w, current_available) via intel-rapl.

    energy_uj is often root-only (post-CVE-2020-8694). When unreadable we
    still try to report the configured power limit so the renderer can show
    "—/110W" instead of nothing.
    """
    if not RAPL_ROOT.exists():
        return 0.0, 0.0, False

    # Limit — prefer the short-term PL2 (burst ceiling, mirrors how GPU reports
    # its absolute power limit). Fall back to PL1 sustained, then HW max spec.
    limit_w = 0.0
    for limit_file_name in (
        "constraint_1_power_limit_uw",   # PL2 short-term turbo limit
        "constraint_0_power_limit_uw",   # PL1 long-term sustained limit
        "constraint_0_max_power_uw",     # HW-spec ceiling (last resort)
    ):
        limit_file = RAPL_ROOT / limit_file_name
        if limit_file.exists():
            try:
                limit_uw = int(limit_file.read_text().strip())
                if limit_uw > 0:
                    limit_w = limit_uw / 1_000_000
                    break
            except (OSError, ValueError, PermissionError):
                continue

    energy_file = RAPL_ROOT / "energy_uj"
    if not energy_file.exists():
        return 0.0, limit_w, False

    now = time.time()
    try:
        energy_uj = int(energy_file.read_text().strip())
    except (PermissionError, OSError, ValueError):
        return 0.0, limit_w, False

    max_energy = 0
    max_file = RAPL_ROOT / "max_energy_range_uj"
    if max_file.exists():
        try:
            max_energy = int(max_file.read_text().strip())
        except (OSError, ValueError):
            pass

    prev: Optional[Dict[str, float]] = None
    if CPU_RAPL_PREV_FILE.exists():
        try:
            prev = json.loads(CPU_RAPL_PREV_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            prev = None

    try:
        CPU_RAPL_PREV_FILE.write_text(json.dumps({"energy_uj": energy_uj, "ts": now}))
    except OSError:
        pass

    if not prev:
        return 0.0, limit_w, True  # available, but no delta yet
    dt = now - float(prev.get("ts", 0))
    de = energy_uj - int(prev.get("energy_uj", 0))
    if de < 0 and max_energy > 0:
        de += max_energy  # wraparound
    if dt <= 0 or de < 0:
        return 0.0, limit_w, True
    watts = round(de / dt / 1_000_000, 1)
    return watts, limit_w, True


def _cpu_fan_pct() -> Tuple[int, bool]:
    """Best-effort CPU fan reading. Returns (pct, available).

    Scans hwmon for known SuperIO/EC chips that publish fan*_input. RPM is
    converted to a rough % using fan*_max where present, else a 2400 RPM ceiling.
    """
    try:
        for hwmon in sorted(HWMON_ROOT.glob("hwmon*")):
            name_file = hwmon / "name"
            if not name_file.exists():
                continue
            try:
                chip = name_file.read_text().strip()
            except OSError:
                continue
            if chip not in _FAN_CHIPS:
                continue
            rpm_file = hwmon / "fan1_input"
            if not rpm_file.exists():
                continue
            try:
                rpm = int(rpm_file.read_text().strip())
            except (OSError, ValueError):
                continue
            max_file = hwmon / "fan1_max"
            ceiling = 2400
            if max_file.exists():
                try:
                    candidate = int(max_file.read_text().strip())
                    if candidate > 0:
                        ceiling = candidate
                except (OSError, ValueError):
                    pass
            pct = int(round(min(100.0, max(0.0, rpm) / ceiling * 100)))
            return pct, True
    except OSError:
        pass
    return 0, False


def _top_processes_by_rss(n: int = 5) -> List[Dict[str, Any]]:
    """Top N processes by resident set size (MiB)."""
    items: List[Dict[str, Any]] = []
    try:
        for entry in PROC_ROOT.iterdir():
            if not entry.name.isdigit():
                continue
            statm = entry / "statm"
            comm = entry / "comm"
            if not statm.exists() or not comm.exists():
                continue
            try:
                parts = statm.read_text().split()
                if len(parts) < 2:
                    continue
                rss_pages = int(parts[1])
                proc_name = comm.read_text().strip()
            except (OSError, ValueError):
                continue
            mem_mib = rss_pages * _PAGE_SIZE // (1024 * 1024)
            if mem_mib < 1 or not proc_name:
                continue
            items.append({"name": proc_name, "mem_mib": mem_mib})
    except OSError:
        return []
    items.sort(key=lambda x: x["mem_mib"], reverse=True)
    return items[:n]


def _read_cache() -> Optional[Dict[str, Any]]:
    if not CACHE_FILE.exists():
        return None
    try:
        age = time.time() - CACHE_FILE.stat().st_mtime
        if age > CACHE_TTL_SECONDS:
            return None
        return json.loads(CACHE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(info: Dict[str, Any]) -> None:
    try:
        CACHE_FILE.write_text(json.dumps(info))
    except OSError:
        pass


def get_cpu_info() -> Dict[str, Any]:
    """Get full CPU snapshot (temp, usage%, RAM%, power, clock, fan, top procs).

    Cached for 3 seconds to keep the statusline cheap. The /proc/stat snapshot
    file is updated EVERY call (not gated by the cache) so CPU% remains accurate.
    """
    cached = _read_cache()
    if cached is not None:
        return cached

    info: Dict[str, Any] = dict(_DEFAULT_INFO)

    # Identity
    info["name"] = _cpu_name()

    # Temperature — prefer hwmon (always fresh) over the thermal DB (history).
    fresh = _from_hwmon() or _from_thermal_db()
    if fresh:
        info.update(fresh)

    # CPU% — /proc/stat delta.
    info["cpu_pct"] = _cpu_usage_pct()

    # RAM% — /proc/meminfo single read.
    ram_pct, ram_used_mib, ram_total_mib = _ram_usage()
    info["ram_pct"] = ram_pct
    info["ram_used_mib"] = ram_used_mib
    info["ram_total_mib"] = ram_total_mib

    # Clock (average across cores)
    info["clock_mhz"] = _cpu_clock_mhz()

    # Power (current + limit). Current may be 0 if RAPL energy_uj is gated to root.
    power_w, power_limit_w, power_available = _cpu_power()
    info["power_w"] = power_w
    info["power_limit_w"] = power_limit_w
    info["power_available"] = power_available

    # Fan (best effort; many desktops/laptops don't expose this)
    fan_pct, fan_available = _cpu_fan_pct()
    info["fan_pct"] = fan_pct
    info["fan_available"] = fan_available

    # Top processes by RSS, with meaningful labels via proc_utils.
    # task-552 Phase 4 hotfix: was [:5], collector capped BEFORE themes.py
    # [:7] could apply. Aggregation downstream merges multi-process apps
    # (firefox → 1 entry) so we need extra headroom upstream to surface
    # 7 distinct entries on busy systems.
    procs = _top_processes_by_rss(15)
    try:
        from proc_utils import resolve_process_label  # type: ignore[import-not-found]
        # _top_processes_by_rss doesn't track PIDs; redo with PIDs and relabel.
        items: list = []
        for entry in PROC_ROOT.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                pid = int(entry.name)
            except ValueError:
                continue
            statm = entry / "statm"
            if not statm.exists():
                continue
            try:
                parts = statm.read_text().split()
                if len(parts) < 2:
                    continue
                rss_pages = int(parts[1])
            except (OSError, ValueError):
                continue
            mem_mib = rss_pages * _PAGE_SIZE // (1024 * 1024)
            if mem_mib < 1:
                continue
            items.append({"pid": pid, "mem_mib": mem_mib})
        items.sort(key=lambda x: x["mem_mib"], reverse=True)
        # task-552 Phase 4 hotfix: collect 15, aggregate downstream → [:7].
        top = items[:15]
        for p in top:
            p["name"] = resolve_process_label(p["pid"])
        info["processes"] = top
    except Exception:
        info["processes"] = procs  # fall back to comm-based labels

    # If we got *any* meaningful signal, mark available.
    if info["temp_c"] > 0 or info["ram_total_mib"] > 0:
        info["available"] = True

    _write_cache(info)
    return info
