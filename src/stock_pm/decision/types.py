"""Shared value objects for the investment decision kernel."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from .numbers import is_finite_number
from .timeparse import as_of_status


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

    def __post_init__(self) -> None:
        table = (self.ref_table or "").strip()
        source = (self.source or "").strip()
        as_of = (self.as_of or "").strip()
        if not table or not source or not as_of:
            raise FactValidationError("FactRef requires ref_table, source, and as_of")
        if self.ref_id is None or str(self.ref_id).strip() == "":
            raise FactValidationError("FactRef requires ref_id")
        stamp = as_of_status(as_of)
        if stamp != "ok":
            raise FactValidationError("FactRef as_of must be a parseable ISO timestamp")


@dataclass(frozen=True)
class MaterialityRule:
    abs_delta: float | None = None
    pct_delta: float | None = None

    def __post_init__(self) -> None:
        for name, value in (("abs_delta", self.abs_delta), ("pct_delta", self.pct_delta)):
            if value is None:
                continue
            if not is_finite_number(value) or value < 0:
                raise FactValidationError(f"{name} must be finite and >= 0")


class FactValidationError(ValueError):
    """OHLC or other raw-fact constraints failed. Do not continue the chain."""


class DecisionConflictError(ValueError):
    """Reserved for caller misuse; kernel functions return status instead."""


SCOPE_GLOBAL = "global"
SCOPE_SECTOR = "sector"
SCOPE_SYMBOL = "symbol"

PRICE_METRICS = frozenset({"close", "open", "high", "low", "price", "last"})
GLOBAL_METRICS = frozenset(
    {
        "cpi",
        "core_cpi",
        "pce",
        "core_pce",
        "inflation",
        "us2y",
        "us_2y",
        "real_rate",
        "real_rates",
        "cut_odds",
        "vix",
        "wti",
        "brent",
        "oil",
        "crude",
        "geopolitics_headline",
    }
)
SYMBOL_METRICS = frozenset(
    {"close", "open", "high", "low", "price", "last", "eps", "revenue", "pe", "opex", "gross_margin"}
)


def infer_scope(metric: str, scope: str | None = None) -> str:
    if scope in {SCOPE_GLOBAL, SCOPE_SECTOR, SCOPE_SYMBOL}:
        return scope
    key = (metric or "").strip().lower()
    if key in GLOBAL_METRICS:
        return SCOPE_GLOBAL
    if key in SYMBOL_METRICS or key in PRICE_METRICS:
        return SCOPE_SYMBOL
    return SCOPE_GLOBAL


def normalize_subject(scope: str | None, subject: str | None) -> str | None:
    if scope == SCOPE_GLOBAL:
        return "global"
    text = (subject or "").strip()
    if not text:
        return None
    if scope == SCOPE_SYMBOL:
        return text.upper()
    return text.lower()


def make_evidence_id(prefix: str, scope: str, subject: str | None, *parts: object) -> str:
    key = normalize_subject(scope, subject) or ""
    tail = "|".join("" if part is None else str(part) for part in parts)
    return f"{prefix}|{scope}|{key}|{tail}"


def fact_ref_is_complete(ref: FactRef | None) -> bool:
    if ref is None:
        return False
    table = (ref.ref_table or "").strip()
    source = (ref.source or "").strip()
    as_of = (ref.as_of or "").strip()
    if ref.ref_id is None or str(ref.ref_id).strip() == "":
        return False
    return bool(table and source and as_of)


def has_provenance(refs: tuple[FactRef, ...] | None) -> bool:
    if not refs:
        return False
    return all(fact_ref_is_complete(ref) for ref in refs)
