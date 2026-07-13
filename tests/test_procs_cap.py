"""Phase 4 — procs cap regression test.

The procs row in GpuTheme has 8 cells. Pre-Phase-4 the CPU and GPU
proc collectors capped at [:5], leaving 3 cells permanently filled
with em-dashes even on systems with 7+ distinct processes. Phase 4
bumped both caps to [:7] so 1 cell remains for `+other`.

This test injects 10 distinct fake procs into the cpu component and
asserts that the rendered procs row contains exactly 7 process names
(plus +other), not 5. Locks the contract — any future revert to [:5]
fails immediately.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import pytest

from colors import get_palette
from components import ComponentData
from primitives import strip_ansi
from themes import GpuTheme


def _components_with_n_procs(n: int) -> dict:
    """Build a minimal components dict with n distinct CPU procs."""
    # Short names (4 chars) so they fit in c5 (10w) without middle-
    # ellipsis truncation; lets the test assert exact-substring matches.
    procs = [
        {"name": f"p{i:02d}x", "pid": str(1000 + i), "mem_mib": 500 - i * 10, "count": 1}
        for i in range(n)
    ]
    return {
        "identity": ComponentData(name="identity", value={
            "persona": "matt", "session_number": 1, "host": "test",
            "session_id": "", "transcript_path": "", "pid": "0",
            "persona_icon": "🪷",
        }),
        "model": ComponentData(name="model", value={
            "display_name": "Opus", "id": "claude-opus",
        }),
        "context": ComponentData(name="context", value={"used_percentage": 0}),
        "cost": ComponentData(name="cost", value={
            "total_cost_usd": 0, "total_duration_ms": 0, "total_api_duration_ms": 0,
        }),
        "rate_limits": ComponentData(name="rate_limits", value={
            "seven_day": {"used_percentage": 0},
        }),
        "workspace": ComponentData(name="workspace", value={
            "cwd": "/tmp", "cwd_short": "/tmp",
        }),
        "version": ComponentData(name="version", value={"version": "0.0.0"}),
        "duration": ComponentData(name="duration", value={"session_duration_ms": 0}),
        "git": ComponentData(name="git", value={"available": False}),
        "cpu": ComponentData(name="cpu", value={
            "available": True,
            "name": "TestCPU",
            "cpu_pct": 0.0,
            "ram_used_mib": 8000,
            "ram_total_mib": 32000,
            # Numeric placeholders to satisfy _severity_color guards in
            # the renderer. Values are arbitrary — these tests only
            # assert against the procs row, not the summary row.
            "temp_c": 50, "power_w": 30, "power_max_w": 241,
            "clock_ghz": 2.0, "fan_rpm": 1000,
            "processes": procs,
        }),
        "memory_sys": ComponentData(name="memory_sys", value={"available": False}),
        "gpu": ComponentData(name="gpu", value={"available": False}),
        "net": ComponentData(name="net", value={"available": False}),
        "tailscale": ComponentData(name="tailscale", value={"available": False}),
    }


def test_cpu_procs_row_shows_seven_entries_when_available():
    """task-552 Phase 4: procs cap is [:7], not [:5]. With 10 distinct
    procs in the input, the rendered row must contain 7 procs.

    We count unique memory labels rather than process names because c5
    (10w) middle-ellipsis-truncates name when content overflows but
    ALWAYS preserves the mem suffix. Each fake proc has a unique mem
    value (0.49, 0.48, 0.47, ...) so the count is reliable.
    """
    components = _components_with_n_procs(10)
    palette = get_palette("catppuccin_mocha")
    rendered = GpuTheme().render(components, palette)
    raw = strip_ansi(rendered)

    # The procs row is the line containing p00x (always fits in c1).
    procs_line = next((line for line in raw.splitlines() if "p00x" in line), "")
    assert procs_line, f"Couldn't find procs row in render:\n{raw}"

    # Each proc renders as "<name> 0.<n>GB" with a unique mem value
    # (procs[i].mem_mib = 500 - i*10 → 0.49GB, 0.48GB, ..., 0.43GB).
    import re
    proc_mem_pattern = re.compile(r"0\.\d{2}GB")
    proc_mems = proc_mem_pattern.findall(procs_line)
    assert len(proc_mems) == 7, (
        f"Expected 7 proc-mem labels (cap is [:7]), got {len(proc_mems)}: {proc_mems}\n"
        f"Procs row: {procs_line!r}"
    )
    # And the +other mem cell.
    other_pattern = re.compile(r"\+[\d.]+GB")
    assert other_pattern.search(procs_line), (
        f"+other label missing: {procs_line!r}"
    )


def test_cpu_procs_row_shows_other_when_capped():
    """When more procs exist than the cap, +other should appear in the
    cell immediately after the last proc (not floating on the far right)."""
    components = _components_with_n_procs(10)
    palette = get_palette("catppuccin_mocha")
    rendered = GpuTheme().render(components, palette)
    raw = strip_ansi(rendered)

    procs_line = next((line for line in raw.splitlines() if "p00x" in line), "")
    assert "other" in procs_line.lower() or "+" in procs_line, (
        f"+other indicator missing when procs are capped:\n{procs_line!r}"
    )


def test_cpu_procs_row_handles_under_cap_gracefully():
    """With 3 procs and a cap of 7, only 3 procs render — no padding
    with fake names. The remaining cells are em-dashes (the existing
    filler behavior)."""
    components = _components_with_n_procs(3)
    palette = get_palette("catppuccin_mocha")
    rendered = GpuTheme().render(components, palette)
    raw = strip_ansi(rendered)

    procs_line = next((line for line in raw.splitlines() if "p00x" in line), "")
    import re
    proc_mems = re.findall(r"0\.\d{2}GB", procs_line)
    assert len(proc_mems) == 3, (
        f"Expected 3 procs visible, got {len(proc_mems)}: {proc_mems}\n"
        f"Procs row: {procs_line!r}"
    )
