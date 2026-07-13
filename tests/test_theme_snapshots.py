"""Golden-file snapshot tests for all 15 themes.

Each test renders the theme against a deterministic mock components dict,
strips ANSI, and asserts the output matches the saved golden file. If a
refactor changes the rendered output, the test fails and the human reviews
the diff. To accept the new output as correct, run:

  UPDATE_SNAPSHOTS=1 pytest tests/test_theme_snapshots.py

Snapshots live in tests/golden/<theme_name>.txt (the "+" in theme names like
"classic+grid" is replaced with "-" for filesystem-friendliness).
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import pytest
from themes import THEME_REGISTRY
from colors import get_palette
from components import ComponentData

GOLDEN_DIR = Path(__file__).parent / "golden"
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

UPDATE_SNAPSHOTS = os.environ.get("UPDATE_SNAPSHOTS", "") == "1"

# Theme name → filename mapping (filesystem can't easily handle "+")
_NAME_TO_FILE = {name: name.replace("+", "-") for name in (t.name for t in THEME_REGISTRY)}

# Theme lookup by name (THEME_REGISTRY is a list[Theme] of instances)
_THEMES_BY_NAME = {t.name: t for t in THEME_REGISTRY}


@pytest.fixture(autouse=True)
def _frozen_env(monkeypatch):
    """Freeze every env var the themes peek at so output is bit-for-bit reproducible.

    Without this, GpuTheme reads CLAUDEMATRIX_AGENT_ID, CLAUDEMATRIX_SESSION_ID,
    PERSONA_SLUG, and falls back to os.getppid()/socket.gethostname(). All four
    must be pinned, or the snapshot diff is meaningless.
    """
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("CLAUDEMATRIX_AGENT_ID", "pid-12345@legion")
    monkeypatch.setenv("CLAUDEMATRIX_SESSION_ID", "00000000-0000-0000-0000-000000000000")
    monkeypatch.setenv("PERSONA_SLUG", "matt")


def _deterministic_components():
    """A frozen mock dict. ALL host-dependent values pinned to constants.

    Notes on pinning choices:
    - workspace.cwd uses a non-existent path. Branch comes from the "git"
      component (pinned to "main" below) — themes never re-probe the cwd.
    - identity.host="legion" overrides socket.gethostname() in GpuTheme.
    - rate_limits uses flat shape (five_hour_pct/seven_day_pct) — the canonical
      output of compute_rate_limits — so themes never branch on missing keys.
    - cost.burn_rate is included for EconomicsTheme (None would force ?
      rendering, which is fine but less informative as a snapshot).
    - "grid" rows use fixed timestamps (HH:MM strings) — _typed("grid") just
      reads them through; never calls time.strftime() at render time.
    """
    return {
        "identity": ComponentData(name="identity", value={
            "persona": "matt",
            "session_number": 674,
            "host": "legion",
            "session_title": "",
            "session_id": "00000000-0000-0000-0000-000000000000",
            "transcript_path": "/snapshot/test/transcript.jsonl",
            "agent_type": "",
            "session_name": "",
            "agent_name": "",
        }),
        "model": ComponentData(name="model", value={
            "display_name": "Opus 4.7 (1M context)",
            "id": "claude-opus-4-7",
        }),
        "context": ComponentData(name="context", value={
            "used_percentage": 42,
            "remaining_percentage": 58,
        }),
        "cost": ComponentData(name="cost", value={
            "total_cost_usd": 4.50,
            "burn_rate": 1.20,
            "total_duration_ms": 4_440_000,
            "total_api_duration_ms": 3_100_000,
        }),
        "rate_limits": ComponentData(name="rate_limits", value={
            "five_hour_pct": 15.0,
            "five_hour_resets": 0,
            "seven_day_pct": 8.0,
            "seven_day_resets": 0,
        }),
        "workspace": ComponentData(name="workspace", value={
            "cwd": "/snapshot/test/cwd",
            "cwd_short": "/snapshot/test/cwd",
            "output_style": "explanatory",
        }),
        "version": ComponentData(name="version", value={"version": "2.1.150"}),
        "duration": ComponentData(name="duration", value={
            "total_ms": 4_440_000,
            "api_ms": 3_100_000,
        }),
        "lines": ComponentData(name="lines", value={"added": 120, "removed": 33}),
        "turn": ComponentData(name="turn", value={
            "duration_ms": 35_000,
            "is_active": True,
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
        "worktree": ComponentData(name="worktree", value={"active": False}),
        "git": ComponentData(name="git", value={
            "is_repo": True,
            "branch": "main",
            "dirty": True,
            "ahead": 2,
            "behind": 0,
            "stash_count": 1,
            "staged": 2,
            "modified": 5,
            "untracked": 3,
        }),
        "topics": ComponentData(name="topics", value={
            "history": ["auth", "database", "api", "testing"],
            "current": "testing",
            "count": 5,
        }),
        "sessions": ComponentData(name="sessions", value={
            "active": {
                "matt:1": {"model": "opus", "cost": 4.50, "persona": "matt"},
                "matt:2": {"model": "sonnet", "cost": 0.40, "persona": "matt"},
            },
            "count": 2,
        }),
        "memory": ComponentData(name="memory", value={
            "hippo": 10000, "koi": 411000, "journal": 29,
            "letta": 4, "messages": 847000, "files": 51,
            "sessions": 242, "total": 1300000,
        }),
        "cache_stats": ComponentData(name="cache_stats", value={
            "creation_tokens": 5000,
            "read_tokens": 2000,
        }),
        "grid": ComponentData(name="grid", value={
            "rows": [
                {"timestamp": "10:15", "emojis": ["🌱", "📝", "🔧"], "cell_count": 3},
                {"timestamp": "10:30", "emojis": ["🔍", "💡"], "cell_count": 2},
            ],
            "total_cells": 5,
            "is_full": False,
        }),
    }


def _render_theme(name: str) -> str:
    """Render the named theme against the deterministic mock and strip ANSI."""
    theme = _THEMES_BY_NAME[name]
    # Use catppuccin_mocha across the board for snapshot consistency. We could
    # use each theme's default_color_scheme, but ANSI is stripped anyway — the
    # palette only affects color codes (which get stripped) plus a few palette
    # symbol choices (separators), which all palettes share.
    palette = get_palette("catppuccin_mocha")
    components = _deterministic_components()
    rendered = theme.render(components, palette)
    return ANSI.sub("", rendered)


@pytest.mark.parametrize("theme_name", sorted(_THEMES_BY_NAME.keys()))
def test_theme_snapshot(theme_name):
    """Assert rendered output of theme matches golden file (or write it on first run)."""
    actual = _render_theme(theme_name)
    golden_path = GOLDEN_DIR / f"{_NAME_TO_FILE[theme_name]}.txt"

    if UPDATE_SNAPSHOTS:
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(actual)
        pytest.skip(f"Snapshot updated for {theme_name} → {golden_path.name}")
        return

    if not golden_path.exists():
        pytest.fail(
            f"Golden file missing for {theme_name}: {golden_path}\n"
            f"Run with UPDATE_SNAPSHOTS=1 to create it."
        )

    expected = golden_path.read_text()
    if actual != expected:
        import difflib
        diff = "\n".join(difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile=str(golden_path),
            tofile="actual",
            lineterm="",
        ))
        pytest.fail(
            f"Snapshot mismatch for {theme_name}:\n{diff}\n\n"
            f"To accept new output: UPDATE_SNAPSHOTS=1 pytest tests/test_theme_snapshots.py"
        )


def test_registry_has_expected_themes():
    """Lock down the registry shape: 16 themes by these exact names."""
    expected = {
        "classic", "hw", "observatory", "zen", "narrative", "fleet",
        "memory_palace", "economics", "git_forge", "heartbeat",
        "archaeologist", "rice", "gpu", "grid", "classic+grid", "gpu+grid",
    }
    assert set(_THEMES_BY_NAME.keys()) == expected, (
        f"Theme registry changed. Missing: {expected - set(_THEMES_BY_NAME.keys())}, "
        f"Extra: {set(_THEMES_BY_NAME.keys()) - expected}"
    )
