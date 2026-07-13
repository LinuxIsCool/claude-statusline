"""Tests for lib/result.py — the Result[T, E] type."""

from __future__ import annotations

import pytest

from result import Err, Ok, err, ok, try_result


def test_ok_constructor_flags():
    r = Ok(42)
    assert r.is_ok() is True
    assert r.is_err() is False


def test_err_constructor_flags():
    r = Err("boom")
    assert r.is_ok() is False
    assert r.is_err() is True


def test_unwrap_on_ok_returns_value():
    assert Ok(7).unwrap() == 7
    assert Ok("hi").unwrap() == "hi"


def test_unwrap_on_err_raises_valueerror():
    with pytest.raises(ValueError) as exc_info:
        Err("nope").unwrap()
    assert "nope" in str(exc_info.value)


def test_unwrap_or_on_err_returns_default():
    assert Err("bad").unwrap_or(99) == 99
    assert Err(RuntimeError("x")).unwrap_or("fallback") == "fallback"


def test_unwrap_or_on_ok_returns_inner():
    assert Ok(1).unwrap_or(99) == 1


def test_map_on_ok_applies_fn():
    r = Ok(3).map(lambda x: x * 2)
    assert isinstance(r, Ok)
    assert r.unwrap() == 6


def test_map_on_err_is_noop():
    e = Err("oops")
    r = e.map(lambda x: x * 2)
    # Same instance — short-circuit
    assert r is e
    assert r.is_err()


def test_and_then_chains_ok_to_ok():
    r = Ok(10).and_then(lambda x: Ok(x + 1)).and_then(lambda x: Ok(x * 2))
    assert isinstance(r, Ok)
    assert r.unwrap() == 22


def test_and_then_short_circuits_on_err():
    calls: list[int] = []

    def step(x: int):
        calls.append(x)
        return Ok(x + 1)

    r = Ok(1).and_then(step).and_then(lambda x: Err("stop")).and_then(step)
    assert r.is_err()
    # The third step (after Err) was never called.
    assert calls == [1]


def test_and_then_err_propagates():
    e = Err("initial")
    r = e.and_then(lambda x: Ok(x + 1))
    assert r is e


def test_try_result_catches_exceptions():
    r = try_result(int, "not-a-number")
    assert r.is_err()
    assert isinstance(r.error, ValueError)


def test_try_result_returns_ok_on_success():
    r = try_result(int, "42")
    assert r.is_ok()
    assert r.unwrap() == 42


def test_try_result_passes_kwargs():
    r = try_result(int, "ff", base=16)
    assert r.is_ok()
    assert r.unwrap() == 255


def test_ok_helper_constructs_ok():
    assert ok(5) == Ok(5)


def test_err_helper_constructs_err():
    assert err("e") == Err("e")


def test_ok_is_frozen():
    o = Ok(1)
    with pytest.raises(Exception):  # FrozenInstanceError
        o.value = 2  # type: ignore[misc]


def test_err_is_frozen():
    e = Err("x")
    with pytest.raises(Exception):
        e.error = "y"  # type: ignore[misc]
