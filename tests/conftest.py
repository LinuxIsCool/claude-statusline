# tests/conftest.py
"""Test fixtures for claude-statusline GpuTheme layout tests.

MockComponents provides a populated ComponentData dict matching real-world
shapes so theme renderers can be exercised against deterministic inputs.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import pytest
from components import ComponentData


@pytest.fixture
def mock_components():
    """A populated components dict mirroring a healthy live session."""
    return {
        "identity": ComponentData(name="identity", value={
            "persona": "matt", "session_number": 674, "host": "legion",
            # Shell-resolved fields (post-refactor: compute_identity owns the
            # env/socket/getppid I/O; tests provide values directly to keep
            # renderers pure). We do NOT preset session_id_short here so tests
            # exercising session_id/transcript_path fallback chains work via
            # the pure derivation inside _row_identity.
            "session_id": "",
            "transcript_path": "",
            "pid": "12345",
        }),
        "model": ComponentData(name="model", value={
            "display_name": "Opus 4.7 (1M context)",
            "id": "claude-opus-4-7",
        }),
        "context": ComponentData(name="context", value={
            "used_percentage": 42, "remaining_percentage": 58,
        }),
        "cost": ComponentData(name="cost", value={
            "total_cost_usd": 4.50,
            "total_duration_ms": 4_440_000,
            "total_api_duration_ms": 3_100_000,
        }),
        "rate_limits": ComponentData(name="rate_limits", value={
            "seven_day": {"used_percentage": 8},
        }),
        "workspace": ComponentData(name="workspace", value={
            "cwd": "/home/user/Workspace/example-app",
            "cwd_short": "~/Workspace/example-app",
            "output_style": "explanatory",
        }),
        "version": ComponentData(name="version", value={"version": "2.1.150"}),
        "duration": ComponentData(name="duration", value={"total_ms": 4_440_000}),
        "lines": ComponentData(name="lines", value={"added": 120, "removed": 33}),
        "turn": ComponentData(name="turn", value={
            "duration_ms": 35_000, "is_active": True,
        }),
        "cpu": ComponentData(name="cpu", value={
            "available": True,
            "name": "Intel i7-13700F",
            "temp_c": 47, "high_c": 80, "critical_c": 100,
            "cpu_pct": 7.0,
            "ram_pct": 42.0,
            "ram_used_mib": 13312, "ram_total_mib": 31744,
            "clock_mhz": 1400,
            "power_w": 22.0, "power_limit_w": 241.0, "power_available": True,
            "fan_pct": 0, "fan_available": False,
            "processes": [
                {"pid": "100", "mem_mib": 700, "name": "firefox"},
                {"pid": "200", "mem_mib": 614, "name": "redis-server"},
                {"pid": "300", "mem_mib": 512, "name": "plasmashell"},
                {"pid": "400", "mem_mib": 410, "name": "preflight"},
                {"pid": "500", "mem_mib": 410, "name": "letta"},
            ],
        }),
        "gpu": ComponentData(name="gpu", value={
            "available": True,
            "name": "NVIDIA RTX 4070",
            "gpu_util": 20,
            "mem_used_mib": 2150, "mem_total_mib": 12282,
            "temp_c": 41,
            "power_w": 16.0, "power_limit_w": 200.0,
            "clock_gpu_mhz": 300,
            "fan_pct": 30,
            "processes": [
                {"pid": "10", "mem_mib": 2354, "name": "whisper"},
                {"pid": "20", "mem_mib": 154, "name": "soffice.bin"},
                {"pid": "30", "mem_mib": 47, "name": "nautilus"},
            ],
            "other_vram_mib": 1800,
            "process_count": 3,
        }),
        "net": ComponentData(name="net", value={
            "available": True,
            "iface": "wlan0", "ssid": "ExampleNet",
            "down_bps": 1_500_000, "up_bps": 384_000,
            "total_down_bytes": 1_794_879_536, "total_up_bytes": 376_737_405,
            "signal_dbm": -69,
            "self_ip": "100.64.0.113",
            "tailscale_peers_online": 0, "tailscale_peers_total": 10,
            "wireguard_tunnels": ["wg0"],
        }),
        "persona": ComponentData(name="persona", value={"slug": "matt", "color": ""}),
        "worktree": ComponentData(name="worktree", value={}),
        "git": ComponentData(name="git", value={
            "is_repo": True,
            "branch": "main",
            "dirty": False,
            "ahead": 0,
            "behind": 0,
            "stash_count": 0,
            "staged": 0,
            "modified": 0,
            "untracked": 0,
        }),
    }


@pytest.fixture
def palette():
    """Return the default catppuccin_mocha palette for tests."""
    from colors import get_palette
    return get_palette("catppuccin_mocha")
