"""Tests for the components shell layer.

These tests pin the Functional Core / Imperative Shell boundary:
compute_identity() is the SHELL — all env-var reads, socket.gethostname()
calls, and os.getppid() fallback live here. Theme renderers are pure
functions of the resulting component dict.

If you find yourself adding env reads to a theme renderer, add them here
instead and write a test below.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import pytest
from payload import StatusPayload


def _payload(**kw) -> StatusPayload:
    """Build a minimal StatusPayload for compute_identity()."""
    return StatusPayload(**kw)


def test_compute_identity_falls_back_when_env_missing(monkeypatch):
    """No CLAUDEMATRIX_* or PERSONA_SLUG env → derive from payload + getppid."""
    monkeypatch.delenv("CLAUDEMATRIX_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDEMATRIX_AGENT_ID", raising=False)
    monkeypatch.delenv("PERSONA_SLUG", raising=False)
    import components
    data = components.compute_identity(
        payload=_payload(session_id="abc123-xyz"),
        state={"persona": "matt"},
    )
    assert data.value["persona"] == "matt"
    # session_id_short derived from payload.session_id when env absent
    assert data.value["session_id_short"] == "abc123-x"
    # pid falls back to os.getppid() — must be a numeric string
    assert data.value["pid"].isdigit()


def test_compute_identity_uses_env_when_walk_finds_no_claude(monkeypatch):
    """CLAUDEMATRIX_SESSION_ID + CLAUDEMATRIX_AGENT_ID are the FALLBACK
    when the process-tree walk doesn't find a claude ancestor (e.g.,
    test runner outside a claude session, headless execution).

    Post-task-552 Phase 2, the walk is PRIMARY: when it finds a claude
    process via /proc, the walked pid wins over CLAUDEMATRIX_AGENT_ID
    (because the env var sometimes encodes the matrix MCP server's pid
    rather than the actual claude CLI process). We patch the resolver
    to return start_pid unchanged here, simulating "no claude found
    in ancestry" — which is exactly what resolve() does when the walk
    fails. This makes the test deterministic regardless of where
    pytest is running.
    """
    monkeypatch.setenv("CLAUDEMATRIX_SESSION_ID", "abc12345xyz-deadbeef")
    monkeypatch.setenv("CLAUDEMATRIX_AGENT_ID", "pid-99999@legion")
    monkeypatch.setenv("PERSONA_SLUG", "shawn")

    # Force the walk to "find nothing" so we exercise env-fallback.
    import pid_resolver
    monkeypatch.setattr(pid_resolver, "resolve",
                        lambda start_pid, session_id="": start_pid)

    import components
    data = components.compute_identity(
        payload=_payload(session_id="payload-id-ignored"),
        state={},  # no persona in state → env's PERSONA_SLUG wins
    )
    assert data.value["persona"] == "shawn"
    assert data.value["session_id_short"] == "abc12345"  # 8-char prefix of env
    assert data.value["pid"] == "99999"  # env fallback wins when walk is empty


def test_compute_identity_walk_wins_over_env_when_claude_found(monkeypatch):
    """task-552 Phase 2 contract: when the process-tree walk locates a
    claude ancestor, that pid wins over CLAUDEMATRIX_AGENT_ID.

    Rationale: CLAUDEMATRIX_AGENT_ID encodes the matrix MCP server's
    pid in some launch configurations, not the actual claude CLI pid.
    The walk via /proc is empirically correct.
    """
    monkeypatch.setenv("CLAUDEMATRIX_SESSION_ID", "session-x-walks")
    monkeypatch.setenv("CLAUDEMATRIX_AGENT_ID", "pid-99999@legion")
    monkeypatch.setenv("PERSONA_SLUG", "shawn")

    # Patch the resolver to "find" a claude ancestor at pid 42424.
    import pid_resolver
    monkeypatch.setattr(pid_resolver, "resolve",
                        lambda start_pid, session_id="": 42424)

    import components
    data = components.compute_identity(payload=_payload(), state={})
    assert data.value["pid"] == "42424", (
        f"Walk should win over env when it finds a claude — got {data.value['pid']!r}"
    )


def test_compute_identity_host_strips_domain(monkeypatch):
    """gethostname() result is split on '.' and only the first label is kept."""
    monkeypatch.delenv("CLAUDEMATRIX_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDEMATRIX_AGENT_ID", raising=False)
    monkeypatch.delenv("PERSONA_SLUG", raising=False)
    import components
    data = components.compute_identity(payload=_payload(), state={})
    host = data.value["host"]
    assert host  # non-empty
    assert "." not in host  # gethostname()'s first segment only


def test_compute_identity_transcript_path_fallback_for_session_id(monkeypatch):
    """When env + payload.session_id both empty, derive from transcript_path basename."""
    monkeypatch.delenv("CLAUDEMATRIX_SESSION_ID", raising=False)
    import components
    data = components.compute_identity(
        payload=_payload(
            session_id="",
            transcript_path="/home/u/.claude/projects/-x/d4c05518-daf5-4b9d.jsonl",
        ),
        state={},
    )
    assert data.value["session_id_short"] == "d4c0551"[:8] or \
           data.value["session_id_short"].startswith("d4c0551")
    # Be explicit: 8-char prefix of "d4c05518-daf5-4b9d" → "d4c05518"
    assert data.value["session_id_short"] == "d4c05518"


def test_compute_identity_question_marks_when_all_sources_absent(monkeypatch):
    """No env, no payload.session_id, no transcript_path → '????????'."""
    monkeypatch.delenv("CLAUDEMATRIX_SESSION_ID", raising=False)
    import components
    data = components.compute_identity(
        payload=_payload(session_id="", transcript_path=""),
        state={},
    )
    assert data.value["session_id_short"] == "????????"


# ── compute_turn / compute_git: the last two I/O migrations ────────────
#
# compute_turn parses the tail of the transcript JSONL to compute the current
# response duration; compute_git subprocess-calls `git rev-parse` via
# git_utils. Both used to live in lib/themes.py (`_get_turn_duration_ms`,
# `_get_branch`) which broke the Functional Core boundary. These tests pin
# the shell layer so renderers stay pure.


def test_compute_turn_returns_zero_when_no_transcript(tmp_path, monkeypatch):
    """Empty transcript_path → duration_ms=0, is_active=False."""
    # Redirect the /tmp cache so a stale prior-run cache can't pollute this test.
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path), raising=False)
    import components
    data = components.compute_turn(payload=_payload(transcript_path=""), state={})
    assert data.value["duration_ms"] == 0
    assert data.value["is_active"] is False


def test_compute_turn_parses_transcript_tail(tmp_path):
    """Write a transcript with one user entry, verify is_active and duration."""
    import json
    from datetime import datetime, timezone, timedelta

    transcript = tmp_path / "session.jsonl"
    user_ts = datetime.now(timezone.utc) - timedelta(seconds=5)
    transcript.write_text(
        json.dumps({"type": "user", "timestamp": user_ts.isoformat()}) + "\n"
    )

    # Bypass the 1s /tmp cache by writing to a unique cache path. Since
    # compute_turn hardcodes /tmp/statusline-turn.json we instead use a
    # transcript whose tail has never been seen — but the cache key isn't
    # per-transcript, so we just clear any pre-existing cache.
    import os
    cache = "/tmp/statusline-turn.json"
    if os.path.exists(cache):
        os.remove(cache)

    import components
    data = components.compute_turn(
        payload=_payload(transcript_path=str(transcript)),
        state={},
    )
    # Only a user entry → assistant still streaming → is_active=True.
    assert data.value["is_active"] is True
    assert data.value["duration_ms"] >= 4_000  # ~5s elapsed since user_ts


def test_compute_git_handles_non_repo(tmp_path):
    """A directory with no .git → is_repo=False."""
    from payload import WorkspaceInfo
    import components
    data = components.compute_git(
        payload=_payload(workspace=WorkspaceInfo(current_dir=str(tmp_path))),
        state={},
    )
    assert data.value.get("is_repo") is False


def test_compute_git_detects_repo(tmp_path):
    """`git init` + a commit + compute_git → is_repo=True, branch='main'."""
    import subprocess

    def _git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True,
                       env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x",
                            "PATH": "/usr/bin:/bin"})

    _git("init", "-q", "-b", "main")
    (tmp_path / "f").write_text("x")
    _git("add", "f")
    _git("commit", "-q", "-m", "x")

    # tmp_path is unique per test → no stale git_utils cache to bust.
    from payload import WorkspaceInfo
    import components
    data = components.compute_git(
        payload=_payload(workspace=WorkspaceInfo(current_dir=str(tmp_path))),
        state={},
    )
    assert data.value.get("is_repo") is True
    assert data.value.get("branch") == "main"
