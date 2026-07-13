"""Tests for event-to-emoji mapping."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import grid_mapper
from grid_mapper import map_event, get_weight, WEIGHT_TABLE, EVENT_KEY_MAP, TOOL_KEY_MAP


@pytest.fixture(autouse=True)
def fixture_flat_file(tmp_path, monkeypatch):
    """Point the mapper at a fixture flat file so mapping behavior is
    verified on any machine. map_event only maps keys present in the flat
    file (the optional claude-emoji export at ~/.claude/local/emoji/);
    without this fixture the tests would depend on host state.
    """
    flat = {key: "•" for key in list(EVENT_KEY_MAP.values()) + list(TOOL_KEY_MAP.values())}
    flat_path = tmp_path / "emoji_flat.json"
    flat_path.write_text(json.dumps(flat), encoding="utf-8")
    monkeypatch.setattr(grid_mapper, "_FLAT_PATH", flat_path)
    monkeypatch.setattr(grid_mapper, "_flat_cache", None)
    monkeypatch.setattr(grid_mapper, "_flat_mtime", 0.0)
    yield
    grid_mapper._flat_cache = None
    grid_mapper._flat_mtime = 0.0


class TestMapEvent:
    def test_session_start(self):
        emoji, key = map_event("SessionStart")
        assert key == "event:session-start"
        assert isinstance(emoji, str)
        assert len(emoji) > 0

    def test_user_prompt(self):
        emoji, key = map_event("UserPromptSubmit")
        assert key == "event:user-prompt-submit"

    def test_tool_specific_override(self):
        emoji, key = map_event("PreToolUse", tool_name="Read")
        assert key == "tool:read"

    def test_tool_specific_bash(self):
        emoji, key = map_event("PreToolUse", tool_name="Bash")
        assert key == "tool:bash"

    def test_unknown_tool_falls_back_to_event(self):
        emoji, key = map_event("PreToolUse", tool_name="SomeUnknownTool")
        assert key == "event:pre-tool-use"

    def test_unknown_event_returns_fallback(self):
        emoji, key = map_event("SomeNewEventType")
        assert emoji == "❓"

    def test_stop(self):
        emoji, key = map_event("Stop")
        assert key == "event:stop"


class TestWeightTable:
    def test_user_prompt_is_heaviest(self):
        assert WEIGHT_TABLE.get("event:user-prompt-submit", 0) == 10

    def test_tool_read_is_lightest(self):
        assert WEIGHT_TABLE.get("tool:read", 0) == 1

    def test_session_start_is_landmark(self):
        assert WEIGHT_TABLE.get("event:session-start", 0) == 8

    def test_get_weight_default(self):
        assert get_weight("unknown:key") == 2


class TestMappingCompleteness:
    def test_all_core_events_mapped(self):
        core_events = [
            "SessionStart", "SessionEnd", "UserPromptSubmit", "Stop",
            "PreToolUse", "PostToolUse", "PostToolUseFailure",
            "SubagentStart", "SubagentStop", "PreCompact", "PostCompact",
            "Notification", "PermissionRequest",
        ]
        for event in core_events:
            assert event in EVENT_KEY_MAP, f"{event} not in EVENT_KEY_MAP"

    def test_all_core_tools_mapped(self):
        core_tools = ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Agent"]
        for tool in core_tools:
            assert tool in TOOL_KEY_MAP, f"{tool} not in TOOL_KEY_MAP"
