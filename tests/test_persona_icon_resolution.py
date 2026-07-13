"""Tests for persona-glyph resolution from the claude-emoji DB.

The golden snapshots only exercise matt (🪷), which happens to be both
the DB-resolved value AND the renderer's safe fallback. That coincidence
hides a real regression class: if the DB lookup silently breaks but
matt's render still happens to show 🪷, all snapshots stay green.

These tests force a non-default persona_icon into the identity component
and assert the rendered output contains it — exercising the actual
resolution path that compute_identity → GpuTheme reads from.

Coverage:
  1. Injected persona_icon flows into rendered output (positive path)
  2. Empty persona_icon falls back to 🪷 (renderer-side safety)
  3. Each persona slug in the canonical emoji DB resolves via the cached
     get_persona_info() path that compute_identity uses
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


# ── Helpers ──────────────────────────────────────────────────────────────

def _identity_value(persona: str = "matt", persona_icon: str = "🪷") -> dict:
    """Build a minimal IdentityValue with the icon under test."""
    return {
        "persona": persona,
        "session_number": 674,
        "host": "legion",
        "session_id": "abcdef01-...",
        "session_id_short": "abcdef01",
        "transcript_path": "",
        "pid": "12345",
        "persona_icon": persona_icon,
    }


def _minimal_components(identity_value: dict) -> dict:
    """Just enough components for GpuTheme to render the identity row."""
    return {
        "identity": ComponentData(name="identity", value=identity_value),
        "model": ComponentData(name="model", value={
            "display_name": "Opus 4.7 (1M context)",
            "id": "claude-opus-4-7",
        }),
        "context": ComponentData(name="context", value={"used_percentage": 42}),
        "cost": ComponentData(name="cost", value={
            "total_cost_usd": 4.50, "total_duration_ms": 0, "total_api_duration_ms": 0,
        }),
        "rate_limits": ComponentData(name="rate_limits", value={
            "seven_day": {"used_percentage": 8},
        }),
        "workspace": ComponentData(name="workspace", value={
            "cwd": "/home/user", "cwd_short": "~",
        }),
        "version": ComponentData(name="version", value={"version": "2.1.150"}),
        "duration": ComponentData(name="duration", value={"session_duration_ms": 0}),
        "git": ComponentData(name="git", value={"available": False}),
        "cpu": ComponentData(name="cpu", value={"available": False}),
        "memory_sys": ComponentData(name="memory_sys", value={"available": False}),
        "gpu": ComponentData(name="gpu", value={"available": False}),
        "net": ComponentData(name="net", value={"available": False}),
        "tailscale": ComponentData(name="tailscale", value={"available": False}),
    }


def _render_first_line(components: dict) -> str:
    """Render with mocha palette, strip ANSI, return the identity row."""
    palette = get_palette("catppuccin_mocha")
    rendered = GpuTheme().render(components, palette)
    return strip_ansi(rendered).splitlines()[0]


# ── Tests ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("slug,icon", [
    ("legion", "🧿"),
    ("sage", "🍵"),
    ("webb", "🕸️"),
    ("wren", "🪽"),
    ("rosa", "🌺"),
])
def test_injected_persona_icon_appears_in_render(slug: str, icon: str):
    """Non-matt icons flow from identity.persona_icon into the identity cell.

    This is the regression-catch for the persona_icon wiring: if compute_identity
    stops populating persona_icon, or if the renderer reverts to a hard-coded
    glyph, this test fails immediately. Matt's snapshot would still pass.
    """
    components = _minimal_components(_identity_value(persona=slug, persona_icon=icon))
    line = _render_first_line(components)
    assert icon in line, (
        f"persona={slug} icon={icon!r} not found in rendered identity row.\n"
        f"Rendered: {line!r}"
    )
    # Matt's lotus must NOT appear when a different persona is active.
    assert "🪷" not in line, (
        f"Matt's lotus leaked into render for persona={slug}: {line!r}"
    )


def test_empty_persona_icon_falls_back_to_lotus():
    """Renderer-side safety: missing icon → 🪷 (matt's signature as safe default).

    Covers the DB-unreachable / unknown-slug case where compute_identity
    surfaces persona_icon="". The `or "🪷"` clause in GpuTheme is the
    last line of defense before the identity row would otherwise render
    "  matt@legion:674" with a leading double-space.
    """
    components = _minimal_components(_identity_value(persona="matt", persona_icon=""))
    line = _render_first_line(components)
    assert "🪷" in line, f"Fallback lotus missing when persona_icon='': {line!r}"


def test_missing_persona_icon_key_falls_back_to_lotus():
    """If a stale identity value lacks the persona_icon key entirely
    (stale cached state, or a partial test fixture), the renderer's
    `iv.get("persona_icon", "")` still works and the lotus appears.
    """
    iv = _identity_value()
    iv.pop("persona_icon")
    components = _minimal_components(iv)
    line = _render_first_line(components)
    assert "🪷" in line, f"Fallback failed when persona_icon key missing: {line!r}"


def test_persona_info_returns_icon_for_registered_slugs(tmp_path, monkeypatch):
    """End-to-end through the cached path that compute_identity uses.

    Builds a fixture emoji DB (same schema as the optional claude-emoji DB)
    so the round-trip is verified on any machine: every persona registered
    under `persona:*` should surface through get_persona_info.
    """
    import sqlite3

    import persona_utils
    from persona_utils import get_persona_info

    sample = {"matt": "🪷", "sage": "🍵", "webb": "🕸️", "legion": "🧿"}
    db_path = tmp_path / "emoji.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE emoji_mappings (entity_key TEXT PRIMARY KEY, emoji TEXT)")
        conn.executemany(
            "INSERT INTO emoji_mappings VALUES (?, ?)",
            [(f"persona:{slug}", icon) for slug, icon in sample.items()],
        )
    monkeypatch.setattr(persona_utils, "EMOJI_DB_PATH", db_path)
    if persona_utils.CACHE_FILE.exists():
        persona_utils.CACHE_FILE.unlink()

    for slug, expected_icon in sample.items():
        info = get_persona_info(slug)
        icon = info.get("icon", "")
        assert icon == expected_icon, (
            f"persona:{slug} returned {icon!r}, expected {expected_icon!r}\n"
            f"Full info dict: {info}"
        )


def test_cache_write_is_atomic_under_concurrency():
    """Concurrent get_persona_info() calls must never produce a truncated
    /tmp cache file. A bare write_text would let a reader observe partial
    JSON during the write window; atomic temp+rename eliminates the race.

    Regression catch: this test would have failed against the original
    bare-write_text implementation under load. With _atomic_write_text, every read sees either the previous full file
    or the new full file — never garbage.
    """
    import json as _json
    import threading
    from persona_utils import CACHE_FILE, get_persona_info

    # Clean slate so every thread starts from a cold cache.
    if CACHE_FILE.exists():
        CACHE_FILE.unlink()

    errors: list[str] = []
    barrier = threading.Barrier(8)

    def worker(slug: str) -> None:
        barrier.wait()  # release all workers simultaneously
        for _ in range(20):
            try:
                info = get_persona_info(slug)
                # Read back independently — must always parse.
                if CACHE_FILE.exists():
                    _json.loads(CACHE_FILE.read_text())
                assert isinstance(info, dict)
                assert info.get("slug") == slug
            except _json.JSONDecodeError as e:
                errors.append(f"{slug}: truncated cache → {e}")
            except Exception as e:
                errors.append(f"{slug}: {type(e).__name__}: {e}")

    threads = [
        threading.Thread(target=worker, args=(s,))
        for s in ["matt", "sage", "webb", "legion",
                  "matt", "sage", "webb", "legion"]
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, (
        f"Concurrent cache writes produced {len(errors)} errors "
        f"(first 3 shown):\n  " + "\n  ".join(errors[:3])
    )
