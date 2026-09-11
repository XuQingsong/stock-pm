"""Shared value objects for the investment decision kernel."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


def to_dict(row: Any) -> dict[str, Any]:
    if hasattr(row, "__dataclass_fields__"):
        payload = asdict(row)
        return payload
    if isinstance(row, Mapping):
        return dict(row)
    raise TypeError(f"unsupported kernel object: {type(row)!r}")


@dataclass(frozen=True)
class FactRef:
    ref_table: str
    ref_id: str | int | None
    as_of: str | None
    source: str | None = None
    text: str | None = None
    synthetic: bool = True


@dataclass(frozen=True)
class MaterialityRule:
    abs_delta: float | None = None
    pct_delta: float | None = None


class FactValidationError(ValueError):
    """OHLC or other raw-fact constraints failed. Do not continue the chain."""


class DecisionConflictError(ValueError):
    """Reserved for caller misuse; kernel functions return status instead."""
