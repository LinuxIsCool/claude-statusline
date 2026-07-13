"""Minimal Result[T, E] type for explicit error-channel handling.

Pattern from Rust's std::result::Result, adapted to Python 3.11+ stdlib-only.
Useful when you want to return "success-or-error" without raising exceptions
through call sites — particularly in the render pipeline where one bad payload
should not blank the whole statusline.

Examples:
    >>> from lib.result import ok, err, try_result
    >>> ok(42).unwrap()
    42
    >>> err("bad").unwrap_or(0)
    0
    >>> ok(2).map(lambda x: x * 10).unwrap()
    20
    >>> try_result(int, "not-a-number").is_err()
    True
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar, Union

T = TypeVar("T")
T2 = TypeVar("T2")
E = TypeVar("E")


@dataclass(frozen=True)
class Ok(Generic[T]):
    """Success case carrying a value of type T."""

    value: T

    def is_ok(self) -> bool:
        return True

    def is_err(self) -> bool:
        return False

    def unwrap(self) -> T:
        """Return the inner value (always succeeds on Ok)."""
        return self.value

    def unwrap_or(self, default: T) -> T:
        """Return the inner value; default is ignored on Ok."""
        return self.value

    def map(self, f: Callable[[T], T2]) -> "Result[T2, E]":
        """Apply f to the inner value, returning a new Ok."""
        return Ok(f(self.value))

    def and_then(self, f: Callable[[T], "Result[T2, E]"]) -> "Result[T2, E]":
        """Chain: apply f (which itself returns a Result) to the inner value."""
        return f(self.value)


@dataclass(frozen=True)
class Err(Generic[E]):
    """Error case carrying an error of type E."""

    error: E

    def is_ok(self) -> bool:
        return False

    def is_err(self) -> bool:
        return True

    def unwrap(self) -> T:
        """Raise ValueError — there is no value to return on Err."""
        raise ValueError(f"Unwrap on Err: {self.error}")

    def unwrap_or(self, default: T) -> T:
        """Return the default — Err carries no value."""
        return default

    def map(self, f: Callable[[T], T2]) -> "Err[E]":
        """No-op on Err — short-circuits the transform chain."""
        return self

    def and_then(self, f: Callable[[T], "Result[T2, E]"]) -> "Err[E]":
        """No-op on Err — short-circuits the chain (propagates the error)."""
        return self


# Discriminated union. Python 3.10+ syntax.
Result = Union[Ok[T], Err[E]]


def ok(value: T) -> Ok[T]:
    """Construct an Ok variant."""
    return Ok(value)


def err(error: E) -> Err[E]:
    """Construct an Err variant."""
    return Err(error)


def try_result(f: Callable[..., T], *args, **kwargs) -> Result[T, Exception]:
    """Execute f(*args, **kwargs); return Ok on success, Err(exc) on failure.

    Example:
        >>> try_result(int, "42").unwrap()
        42
        >>> try_result(int, "nope").is_err()
        True
    """
    try:
        return Ok(f(*args, **kwargs))
    except Exception as e:
        return Err(e)
