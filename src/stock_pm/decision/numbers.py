"""Numeric helpers that never coerce missing values to zero."""

from __future__ import annotations

import math
from typing import Any

from stock_pm.analytics import _number


def as_number(value: Any) -> float | None:
    number = _number(value)
    if number is None or not math.isfinite(number):
        return None
    return number


def is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


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
