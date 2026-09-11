"""Numeric helpers that never coerce missing values to zero."""

from __future__ import annotations

from typing import Any

from stock_pm.analytics import _number


def as_number(value: Any) -> float | None:
    return _number(value)


def signed_delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return current - previous


def pct_delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    if previous == 0:
        return None
    return (current - previous) / abs(previous) * 100.0


def round_pct(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(value, digits)
