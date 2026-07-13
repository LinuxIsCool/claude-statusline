"""Phase 4 — network diagnostics tests.

Covers:
  - _read_default_gateway() — parse /proc/net/route's hex gateway field
  - _measure_latency_ms() — TCP-connect probe with timeout
  - _latency_cache read/write — 10s TTL atomic /tmp cache
  - get_net_info() includes latency_ms in the returned dict

The measurement function uses socket.create_connection. We patch it
rather than hitting the real network so tests are deterministic and
don't require an internet connection.
"""
from __future__ import annotations

import json
import socket as _real_socket
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import pytest

import net_utils


# ── Gateway discovery ────────────────────────────────────────────────

def test_default_gateway_parses_proc_net_route(tmp_path, monkeypatch):
    """The gateway field in /proc/net/route is a little-endian hex
    representation of the IPv4 address. Parser must reverse byte pairs
    and decode as dotted quad."""
    fake_route = tmp_path / "route"
    fake_route.write_text(
        "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
        "enp4s0\t00000000\tFE01A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0\n"
    )
    monkeypatch.setattr(net_utils, "PROC_NET_ROUTE", fake_route)
    assert net_utils._read_default_gateway() == "192.168.1.254"


def test_default_gateway_handles_missing_default_route(tmp_path, monkeypatch):
    """If /proc/net/route has no default route (00000000 destination),
    return empty string."""
    fake_route = tmp_path / "route"
    fake_route.write_text(
        "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
        "enp4s0\t01A8C0FE\t00000000\t0001\t0\t0\t100\t00FFFFFF\t0\t0\t0\n"
    )
    monkeypatch.setattr(net_utils, "PROC_NET_ROUTE", fake_route)
    assert net_utils._read_default_gateway() == ""


def test_default_gateway_handles_missing_file(tmp_path, monkeypatch):
    """No /proc/net/route → empty string, never raises."""
    monkeypatch.setattr(net_utils, "PROC_NET_ROUTE", tmp_path / "does-not-exist")
    assert net_utils._read_default_gateway() == ""


# ── Latency measurement ──────────────────────────────────────────────

def test_measure_latency_returns_milliseconds():
    """A successful TCP connect must return a positive float (ms)."""
    fake_sock = type("FS", (), {"close": lambda self: None})()
    with patch("socket.create_connection", return_value=fake_sock):
        result = net_utils._measure_latency_ms("192.168.1.254")
    assert result is not None
    assert isinstance(result, float)
    assert result >= 0.0


def test_measure_latency_returns_none_on_timeout():
    """A timed-out connection must return None, not raise."""
    def _raise_timeout(*args, **kwargs):
        raise _real_socket.timeout("connection timed out")
    with patch("socket.create_connection", side_effect=_raise_timeout):
        assert net_utils._measure_latency_ms("192.168.1.254") is None


def test_measure_latency_returns_none_on_refused():
    """A connection refused must return None (gateway exists but no
    listener on the probe port)."""
    with patch("socket.create_connection", side_effect=ConnectionRefusedError()):
        assert net_utils._measure_latency_ms("192.168.1.254") is None


def test_measure_latency_returns_none_on_empty_gateway():
    """No gateway IP → no probe → None (avoid trying to connect to '')."""
    assert net_utils._measure_latency_ms("") is None


def test_measure_latency_returns_none_on_oserror():
    """Any OSError (DNS failure, network unreachable, etc.) → None."""
    with patch("socket.create_connection", side_effect=OSError("network unreachable")):
        assert net_utils._measure_latency_ms("10.0.0.1") is None


# ── Latency cache ────────────────────────────────────────────────────

def test_latency_cache_round_trip(tmp_path, monkeypatch):
    """Write a latency value; read it back; value matches."""
    monkeypatch.setattr(net_utils, "LATENCY_CACHE_FILE", tmp_path / "lat.json")
    net_utils._write_latency_cache(2.5)
    assert net_utils._read_latency_cache() == 2.5


def test_latency_cache_returns_none_when_stale(tmp_path, monkeypatch):
    """A cache file older than LATENCY_CACHE_TTL returns None."""
    cache_file = tmp_path / "lat.json"
    cache_file.write_text(json.dumps({"latency_ms": 5.0, "ts": time.time() - 999}))
    # Manually set mtime to be far in the past
    import os
    os.utime(cache_file, (time.time() - 999, time.time() - 999))
    monkeypatch.setattr(net_utils, "LATENCY_CACHE_FILE", cache_file)
    assert net_utils._read_latency_cache() is None


def test_latency_cache_handles_corrupted_json(tmp_path, monkeypatch):
    """A truncated cache file must not crash the reader."""
    cache_file = tmp_path / "lat.json"
    cache_file.write_text('{"latency_ms": 2.5')  # truncated
    monkeypatch.setattr(net_utils, "LATENCY_CACHE_FILE", cache_file)
    assert net_utils._read_latency_cache() is None


def test_latency_cache_preserves_null(tmp_path, monkeypatch):
    """Caching a None (probe failed) value must round-trip as None,
    distinguishable from 'cache miss' via the cache file's existence."""
    monkeypatch.setattr(net_utils, "LATENCY_CACHE_FILE", tmp_path / "lat.json")
    net_utils._write_latency_cache(None)
    # The reader returns None either way (cache hit None or no cache),
    # but the file must exist (we cached the failed-probe result).
    assert (tmp_path / "lat.json").exists()
    assert net_utils._read_latency_cache() is None


# ── get_net_info integration ─────────────────────────────────────────

def test_net_info_includes_latency_ms_field():
    """The default info dict must declare latency_ms so callers can
    safely read it with a .get() default."""
    info = dict(net_utils._DEFAULT_INFO)
    assert "latency_ms" in info
    assert info["latency_ms"] is None  # null until measured
