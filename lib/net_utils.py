# lib/net_utils.py
"""Networking metrics for claude-statusline GpuTheme.

All sources are non-sudo:
  /proc/net/dev       — byte counters (delta vs prev snapshot)
  /proc/net/wireless  — WiFi signal quality + dBm
  /sys/class/net/*    — interface enumeration (incl. tailscale*, wg*)
  nmcli               — active SSID resolution (iwgetid not installed on CachyOS)
  tailscale status --json   — peer count, self IP
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# subprocess_caps lives in the same lib/ directory.
sys.path.insert(0, str(Path(__file__).parent))
from subprocess_caps import with_blackout  # noqa: E402

CACHE_TTL_SECONDS = 3
CACHE_FILE = Path("/tmp/statusline-net.json")
PREV_FILE = Path("/tmp/statusline-net-prev.json")
SLOW_CACHE_TTL = 30
SLOW_CACHE_FILE = Path("/tmp/statusline-net-slow.json")


def _atomic_write_text(path: Path, content: str) -> None:
    """Write content to path atomically via temp file + rename.

    POSIX guarantees os.rename() atomicity within the same filesystem, so
    a concurrent reader will never observe a partially-written file.
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

PROC_NET_DEV = Path("/proc/net/dev")
PROC_NET_WIRELESS = Path("/proc/net/wireless")
PROC_NET_ROUTE = Path("/proc/net/route")
SYS_CLASS_NET = Path("/sys/class/net")

_DEFAULT_INFO: Dict[str, Any] = {
    "available": False,
    "iface": "?", "ssid": "",
    "down_bps": 0, "up_bps": 0,
    "total_down_bytes": 0, "total_up_bytes": 0,
    "signal_dbm": None,
    "latency_ms": None,  # task-552 Phase 4: gateway:53 TCP-connect probe
    "self_ip": "", "tailscale_peers_online": 0, "tailscale_peers_total": 0,
    "tailscale_available": False,
    "wireguard_tunnels": [],
}


# task-552 Phase 4 — latency cache. Probe runs at most once per
# LATENCY_CACHE_TTL seconds; renders within the TTL re-use the cached
# value. Separate from the main net cache because the probe is the
# most expensive operation in get_net_info (up to LATENCY_TIMEOUT
# seconds when the gateway is unreachable) — caching it longer than
# the rest of the net dict is the right tradeoff.
LATENCY_CACHE_FILE = Path("/tmp") / f"statusline-latency-{os.getuid()}.json"
LATENCY_CACHE_TTL = 10  # seconds — gateway latency is slow-changing
LATENCY_TIMEOUT = 0.3  # seconds — render budget guard
LATENCY_PROBE_PORT = 53  # DNS — virtually every consumer router listens


def _read_default_iface() -> str:
    """Find the iface used for the default route by parsing /proc/net/route."""
    try:
        with PROC_NET_ROUTE.open() as f:
            f.readline()  # header
            for line in f:
                parts = line.split()
                if len(parts) >= 3 and parts[1] == "00000000":
                    return parts[0]
    except OSError:
        pass
    return ""


def _read_default_gateway() -> str:
    """Resolve the IPv4 gateway from /proc/net/route.

    The Gateway field is a little-endian hex IPv4. Example:
        "FE01A8C0" → bytes [FE, 01, A8, C0] reversed → "192.168.1.254"

    Returns "" when no default route is present or parsing fails.
    Never raises.
    """
    try:
        with PROC_NET_ROUTE.open() as f:
            f.readline()  # header
            for line in f:
                parts = line.split()
                # Default route: destination = 00000000, gateway != 00000000
                if len(parts) >= 3 and parts[1] == "00000000" and parts[2] != "00000000":
                    gw_hex = parts[2]
                    if len(gw_hex) != 8:
                        return ""
                    # Reverse byte pairs and decode as dotted quad.
                    try:
                        octets = [int(gw_hex[i:i+2], 16) for i in (6, 4, 2, 0)]
                        return ".".join(str(o) for o in octets)
                    except ValueError:
                        return ""
    except OSError:
        pass
    return ""


def _measure_latency_ms(gateway: str) -> Optional[float]:
    """Measure round-trip latency to `gateway:53` via TCP-connect.

    DNS port 53 is virtually always open on consumer routers. TCP-
    connect timing reflects the time for the three-way handshake to
    complete — a reasonable proxy for one-way latency.

    Returns the elapsed time in milliseconds (float) on success, or
    None on any failure (timeout, connection refused, OSError, empty
    gateway). Never raises. Bounded by LATENCY_TIMEOUT.
    """
    if not gateway:
        return None
    import socket as _sock
    start = time.perf_counter()
    try:
        conn = _sock.create_connection((gateway, LATENCY_PROBE_PORT), timeout=LATENCY_TIMEOUT)
        try:
            conn.close()
        except OSError:
            pass
    except (_sock.timeout, ConnectionRefusedError, OSError):
        return None
    return (time.perf_counter() - start) * 1000.0


def _read_latency_cache() -> Optional[float]:
    """Return the cached latency_ms if fresh, else None.

    Note: a cached value of None is a valid measurement (probe failed
    recently — don't re-probe for LATENCY_CACHE_TTL seconds). Callers
    distinguish "cache miss vs cached-None" by checking file existence
    separately if needed; for get_net_info, both produce the same
    rendered output, so the conflation is fine.
    """
    if not LATENCY_CACHE_FILE.exists():
        return None
    try:
        if time.time() - LATENCY_CACHE_FILE.stat().st_mtime > LATENCY_CACHE_TTL:
            return None
        data = json.loads(LATENCY_CACHE_FILE.read_text())
        if isinstance(data, dict):
            val = data.get("latency_ms")
            return float(val) if isinstance(val, (int, float)) else None
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return None


def _write_latency_cache(latency_ms: Optional[float]) -> None:
    """Persist the probe result (including None) atomically."""
    payload = {"latency_ms": latency_ms, "ts": time.time()}
    try:
        _atomic_write_text(LATENCY_CACHE_FILE, json.dumps(payload))
    except OSError:
        pass


def _read_proc_net_dev() -> Dict[str, Dict[str, int]]:
    """Parse /proc/net/dev → {iface: {rx_bytes, tx_bytes}}."""
    out: Dict[str, Dict[str, int]] = {}
    try:
        with PROC_NET_DEV.open() as f:
            f.readline()  # header 1
            f.readline()  # header 2
            for line in f:
                if ":" not in line:
                    continue
                name, rest = line.split(":", 1)
                fields = rest.split()
                if len(fields) >= 9:
                    out[name.strip()] = {
                        "rx_bytes": int(fields[0]),
                        "tx_bytes": int(fields[8]),
                    }
    except OSError:
        pass
    return out


def _read_wireless_signal(iface: str) -> Optional[int]:
    """Return signal level in dBm for a WiFi iface (or None for wired)."""
    try:
        with PROC_NET_WIRELESS.open() as f:
            f.readline()  # header 1
            f.readline()  # header 2
            for line in f:
                if iface in line:
                    parts = line.split()
                    if len(parts) >= 4:
                        # Column 3 = link quality, column 4 = signal level dBm
                        sig = parts[3].rstrip(".")
                        try:
                            return int(float(sig))
                        except ValueError:
                            return None
    except OSError:
        pass
    return None


def _read_ssid(iface: str) -> str:
    """Resolve the SSID for a WiFi iface via `nmcli`.

    Guarded by subprocess_caps.with_blackout so a wedged nmcli only costs us
    the first 1s timeout; the next 60s of renders skip the call entirely.
    """
    def _run() -> str:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,DEVICE,TYPE", "connection", "show", "--active"],
            capture_output=True, text=True, timeout=1.0,
        )
        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, "nmcli")
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[1] == iface and "wireless" in parts[2]:
                return parts[0]
        return ""

    return with_blackout("nmcli", _run, "")


def _read_wireguard_tunnels() -> List[str]:
    """Enumerate WireGuard interfaces from /sys/class/net (tailscale* or wg*)."""
    out: List[str] = []
    try:
        for entry in SYS_CLASS_NET.iterdir():
            name = entry.name
            if name.startswith("wg") or name.startswith("tailscale"):
                out.append(name)
    except OSError:
        pass
    return sorted(out)


def _query_tailscale() -> Dict[str, Any]:
    """Run `tailscale status --json` and parse peer info.

    Returns a dict with self_ip, peers_online, peers_total, tailscale_available.
    Guarded by subprocess_caps.with_blackout (60s skip after timeout) AND
    a 30s slow-cache (skip re-invocation across consecutive renders).
    """
    cached = _read_slow_cache()
    if cached is not None:
        return cached

    fallback = {
        "self_ip": "",
        "peers_online": 0,
        "peers_total": 0,
        "tailscale_available": False,
    }

    def _run() -> Dict[str, Any]:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True, text=True, timeout=2.0,
        )
        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, "tailscale")
        data = json.loads(result.stdout)
        out: Dict[str, Any] = {"self_ip": "", "peers_online": 0, "peers_total": 0}
        ips = data.get("Self", {}).get("TailscaleIPs", [])
        if ips:
            out["self_ip"] = ips[0]
        peers = data.get("Peer", {}) or {}
        out["peers_total"] = len(peers)
        out["peers_online"] = sum(1 for p in peers.values() if p.get("Online"))
        # F2: explicit capability bit. tailscale CLI returns {} (exit 0) when
        # the daemon is down — no exception, no error text. data.get("Self")
        # is the canonical signal that the daemon is reachable.
        out["tailscale_available"] = bool(data.get("Self"))
        return out

    info = with_blackout("tailscale", _run, fallback)
    _write_slow_cache(info)
    return info


def _read_slow_cache() -> Optional[Dict[str, Any]]:
    if not SLOW_CACHE_FILE.exists():
        return None
    try:
        if time.time() - SLOW_CACHE_FILE.stat().st_mtime > SLOW_CACHE_TTL:
            return None
        return json.loads(SLOW_CACHE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_slow_cache(info: Dict[str, Any]) -> None:
    try:
        _atomic_write_text(SLOW_CACHE_FILE, json.dumps(info))
    except OSError:
        pass


def _read_cache() -> Optional[Dict[str, Any]]:
    if not CACHE_FILE.exists():
        return None
    try:
        if time.time() - CACHE_FILE.stat().st_mtime > CACHE_TTL_SECONDS:
            return None
        return json.loads(CACHE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(info: Dict[str, Any]) -> None:
    try:
        _atomic_write_text(CACHE_FILE, json.dumps(info))
    except OSError:
        pass


def get_net_info() -> Dict[str, Any]:
    """Return current networking snapshot, cached 3s."""
    cached = _read_cache()
    if cached is not None:
        return cached

    info: Dict[str, Any] = dict(_DEFAULT_INFO)
    iface = _read_default_iface() or "?"
    info["iface"] = iface

    dev = _read_proc_net_dev()
    now = time.time()
    if iface in dev:
        cur_rx = dev[iface]["rx_bytes"]
        cur_tx = dev[iface]["tx_bytes"]
        info["total_down_bytes"] = cur_rx
        info["total_up_bytes"] = cur_tx
        # Compute rates from prev snapshot, keyed by iface so an iface switch
        # (e.g., enp4s0 → wlan0) doesn't cause negative deltas.
        prev_map: Dict[str, Dict[str, Any]] = {}
        if PREV_FILE.exists():
            try:
                raw = json.loads(PREV_FILE.read_text())
                if isinstance(raw, dict):
                    # Legacy flat-dict snapshots (with "rx"/"tx"/"ts" at top) are
                    # ignored; only iface-keyed entries are accepted.
                    for k, v in raw.items():
                        if isinstance(v, dict) and "rx" in v and "tx" in v and "ts" in v:
                            prev_map[k] = v
            except (OSError, json.JSONDecodeError):
                prev_map = {}
        prev_for_iface = prev_map.get(iface)

        # Update this iface's snapshot, cap total entries at 4 (drop oldest by ts).
        prev_map[iface] = {"rx": cur_rx, "tx": cur_tx, "ts": now}
        if len(prev_map) > 4:
            sorted_ifaces = sorted(prev_map.items(), key=lambda kv: float(kv[1].get("ts", 0)))
            for stale_iface, _ in sorted_ifaces[: len(prev_map) - 4]:
                prev_map.pop(stale_iface, None)
        try:
            _atomic_write_text(PREV_FILE, json.dumps(prev_map))
        except OSError:
            pass

        if prev_for_iface:
            dt = now - float(prev_for_iface.get("ts", 0))
            if dt > 0:
                info["down_bps"] = max(0, int((cur_rx - int(prev_for_iface.get("rx", 0))) * 8 / dt))
                info["up_bps"] = max(0, int((cur_tx - int(prev_for_iface.get("tx", 0))) * 8 / dt))

    if iface.startswith(("wlan", "wlp")):
        info["ssid"] = _read_ssid(iface)
        info["signal_dbm"] = _read_wireless_signal(iface)

    info["wireguard_tunnels"] = _read_wireguard_tunnels()

    # Gateway latency — cached separately so the heavy probe runs at
    # most once per LATENCY_CACHE_TTL seconds, regardless of how often
    # the main net cache expires.
    latency = _read_latency_cache()
    if latency is None and not LATENCY_CACHE_FILE.exists():
        gw = _read_default_gateway()
        latency = _measure_latency_ms(gw)
        _write_latency_cache(latency)
    info["latency_ms"] = latency

    ts = _query_tailscale()
    info["self_ip"] = ts.get("self_ip", "")
    info["tailscale_peers_online"] = ts.get("peers_online", 0)
    info["tailscale_peers_total"] = ts.get("peers_total", 0)
    # F2: explicit capability bit. Lets themes distinguish "daemon down" (show
    # `tailscale:offline`) from "daemon up, no peers" (show `0/0`). Without
    # this, a wedged daemon looks identical to a healthy-but-lonely mesh.
    info["tailscale_available"] = bool(ts.get("tailscale_available", False))

    info["available"] = bool(iface and iface != "?")
    _write_cache(info)
    return info
