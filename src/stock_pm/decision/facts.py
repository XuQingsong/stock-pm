"""Fact-layer checks. Invalid raw facts must not enter later layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .numbers import as_number
from .types import FactValidationError


@dataclass(frozen=True)
class OhlcCheck:
    ok: bool
    errors: tuple[str, ...]
    bar: dict[str, Any]


def validate_ohlc(bar: dict[str, Any] | None) -> OhlcCheck:
    row = dict(bar or {})
    open_px = as_number(row.get("open") if "open" in row else row.get("open_price"))
    high = as_number(row.get("high") if "high" in row else row.get("high_price"))
    low = as_number(row.get("low") if "low" in row else row.get("low_price"))
    close = as_number(row.get("close") if "close" in row else row.get("close_price"))
    errors: list[str] = []
    if None in (open_px, high, low, close):
        errors.append("ohlc_incomplete")
        return OhlcCheck(ok=False, errors=tuple(errors), bar=row)
    assert open_px is not None and high is not None and low is not None and close is not None
    if high < low:
        errors.append("high_lt_low")
    if high < open_px:
        errors.append("high_lt_open")
    if high < close:
        errors.append("high_lt_close")
    if low > open_px:
        errors.append("low_gt_open")
    if low > close:
        errors.append("low_gt_close")
    return OhlcCheck(ok=not errors, errors=tuple(errors), bar=row)


def require_valid_bar(bar: dict[str, Any] | None) -> dict[str, Any]:
    check = validate_ohlc(bar)
    if not check.ok:
        raise FactValidationError(
            "OHLC failed fact validation: " + ", ".join(check.errors)
        )
    return check.bar
