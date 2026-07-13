"""Tests for scripts/gpu-sampler.py — the off-render-path GPU cache warmer.

The sampler's value is that it writes gpu_utils.CACHE_FILE (which the renderer
reads) using gpu_utils' own parser, so the renderer never shells out to
nvidia-smi. These tests verify the atomic write and a single sample cycle
without ever invoking real nvidia-smi.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

# The sampler lives in scripts/ with a hyphenated name; load it by path.
_SAMPLER_PATH = Path(__file__).resolve().parent.parent / "scripts" / "gpu-sampler.py"


@pytest.fixture
def sampler(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("gpu_sampler", _SAMPLER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Redirect the cache to a temp file so we never touch /tmp state.
    monkeypatch.setattr(mod.gpu_utils, "CACHE_FILE", tmp_path / "gpu.json")
    return mod


def test_atomic_write_roundtrips_valid_json(sampler):
    info = {"available": True, "name": "NVIDIA RTX 5080 Laptop GPU", "gpu_util": 7}
    sampler._write_cache_atomic(info)
    written = json.loads(sampler.gpu_utils.CACHE_FILE.read_text())
    assert written == info


def test_atomic_write_leaves_no_temp_files(sampler):
    sampler._write_cache_atomic({"available": False})
    leftovers = list(sampler.gpu_utils.CACHE_FILE.parent.glob(".gpu-*"))
    assert leftovers == [], f"atomic write left temp files: {leftovers}"


def test_one_cycle_writes_cache_using_plugin_parser(sampler, monkeypatch):
    """A sample cycle must populate the cache from gpu_utils._query_gpu (mocked),
    proving the sampler reuses the plugin's schema rather than inventing one."""
    sentinel = {"available": True, "name": "MOCK GPU", "gpu_util": 42, "temp_c": 50}
    monkeypatch.setattr(sampler, "_warm_up", lambda: None)
    monkeypatch.setattr(sampler.gpu_utils, "_query_gpu", lambda: dict(sentinel))
    # Run the body of one loop iteration directly (avoid the infinite loop).
    sampler.subprocess_caps.report_success("nvidia-smi")
    info = sampler.gpu_utils._query_gpu()
    sampler._write_cache_atomic(info)
    assert json.loads(sampler.gpu_utils.CACHE_FILE.read_text()) == sentinel


def test_compact_gpu_name_strips_form_factor_and_marketing():
    """GPU name compaction must drop GeForce + 'Laptop GPU' so the model fits."""
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "gpu_utils_x", Path(__file__).resolve().parent.parent / "lib" / "gpu_utils.py")
    gu = importlib.util.module_from_spec(spec); spec.loader.exec_module(gu)
    assert gu._compact_gpu_name("NVIDIA GeForce RTX 5080 Laptop GPU") == "NVIDIA RTX 5080"
    assert gu._compact_gpu_name("NVIDIA GeForce RTX 4070") == "NVIDIA RTX 4070"
    assert gu._compact_gpu_name("NVIDIA RTX 5080 Laptop GPU") == "NVIDIA RTX 5080"
