"""Fact-layer checks. Invalid raw facts must not enter later layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .numbers import as_number, is_finite_number
from .timeparse import as_of_status
from .types import (
    PRICE_METRICS,
    SCOPE_GLOBAL,
    SCOPE_SYMBOL,
    FactRef,
    FactValidationError,
    infer_scope,
    normalize_subject,
)

PRICE_METRICS = PRICE_METRICS


@dataclass(frozen=True)
class OhlcCheck:
    ok: bool
    errors: tuple[str, ...]
    bar: dict[str, Any]


def ohlc_constraint_errors(open_px: Any, high: Any, low: Any, close: Any) -> list[str]:
    errors: list[str] = []
    if not all(is_finite_number(value) for value in (open_px, high, low, close)):
        errors.append("ohlc_incomplete")
        return errors
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
    return errors


def _require_identity(scope: str, subject: str | None, *, label: str) -> str:
    resolved = normalize_subject(scope, subject)
    if scope == SCOPE_SYMBOL and not resolved:
        raise FactValidationError(f"{label} with symbol scope requires subject")
    if scope == SCOPE_GLOBAL:
        return "global"
    if not resolved:
        raise FactValidationError(f"{label} requires subject")
    return resolved


@dataclass(frozen=True)
class ValidatedBar:
    """OHLC that has already passed inequality checks. Required for price Change."""

    as_of: str | None
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    refs: tuple[FactRef, ...] = ()
    scope: str = SCOPE_SYMBOL
    subject: str | None = None
    synthetic: bool = True

    def __post_init__(self) -> None:
        errors = ohlc_constraint_errors(self.open, self.high, self.low, self.close)
        if errors:
            raise FactValidationError("OHLC failed fact validation: " + ", ".join(errors))
        if self.volume is not None and not is_finite_number(self.volume):
            raise FactValidationError("OHLC failed fact validation: volume_non_finite")
        stamp = as_of_status(self.as_of)
        if stamp == "missing_as_of":
            raise FactValidationError("ValidatedBar requires as_of")
        if stamp == "invalid_as_of":
            raise FactValidationError("ValidatedBar as_of is not a parseable ISO timestamp")
        resolved = _require_identity(self.scope, self.subject, label="ValidatedBar")
        object.__setattr__(self, "subject", resolved)

    def price_for(self, metric: str) -> float:
        key = (metric or "").strip().lower()
        if key in {"close", "price", "last"}:
            return self.close
        if key == "open":
            return self.open
        if key == "high":
            return self.high
        if key == "low":
            return self.low
        raise TypeError(f"ValidatedBar has no price field for metric {metric!r}")


@dataclass(frozen=True)
class ValidatedFact:
    """Finite numeric fact. Optional controlled entry for non-price series."""

    metric: str
    value: float
    as_of: str | None
    unit: str | None = None
    refs: tuple[FactRef, ...] = ()
    scope: str | None = None
    subject: str | None = None
    synthetic: bool = True

    def __post_init__(self) -> None:
        if not (self.metric or "").strip():
            raise FactValidationError("numeric fact metric is required")
        if not is_finite_number(self.value):
            raise FactValidationError(f"numeric fact {self.metric!r} is missing or non-finite")
        if not (self.as_of or "").strip():
            raise FactValidationError(f"numeric fact {self.metric!r} requires as_of")
        if as_of_status(self.as_of) != "ok":
            raise FactValidationError(f"numeric fact {self.metric!r} as_of is not a parseable ISO timestamp")
        scope = infer_scope(self.metric, self.scope)
        object.__setattr__(self, "scope", scope)
        resolved = _require_identity(scope, self.subject, label="ValidatedFact")
        object.__setattr__(self, "subject", resolved)


def validate_ohlc(bar: dict[str, Any] | None) -> OhlcCheck:
    row = dict(bar or {})
    open_px = as_number(row.get("open") if "open" in row else row.get("open_price"))
    high = as_number(row.get("high") if "high" in row else row.get("high_price"))
    low = as_number(row.get("low") if "low" in row else row.get("low_price"))
    close = as_number(row.get("close") if "close" in row else row.get("close_price"))
    errors = ohlc_constraint_errors(open_px, high, low, close)
    return OhlcCheck(ok=not errors, errors=tuple(errors), bar=row)


def _nonempty_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bar_row_subject(row: dict[str, Any], *, scope: str) -> str | None:
    subject = _nonempty_text(row.get("subject"))
    symbol = _nonempty_text(row.get("symbol"))
    if subject and symbol and normalize_subject(scope, subject) != normalize_subject(scope, symbol):
        raise FactValidationError("identity_override")
    return subject or symbol


def require_valid_bar(
    bar: dict[str, Any] | None,
    *,
    refs: tuple[FactRef, ...] | None = None,
    scope: str | None = None,
    subject: str | None = None,
) -> ValidatedBar:
    check = validate_ohlc(bar)
    if not check.ok:
        raise FactValidationError(
            "OHLC failed fact validation: " + ", ".join(check.errors)
        )
    row = check.bar
    open_px = as_number(row.get("open") if "open" in row else row.get("open_price"))
    high = as_number(row.get("high") if "high" in row else row.get("high_price"))
    low = as_number(row.get("low") if "low" in row else row.get("low_price"))
    close = as_number(row.get("close") if "close" in row else row.get("close_price"))
    volume = as_number(row.get("volume"))
    as_of = row.get("as_of") or row.get("date") or row.get("bar_date")
    as_of_text = None if as_of is None else str(as_of)
    assert open_px is not None and high is not None and low is not None and close is not None
    row_scope = _nonempty_text(row.get("scope"))
    param_scope = _nonempty_text(scope)
    param_subject = _nonempty_text(subject)
    if param_scope is not None and row_scope is not None and param_scope != row_scope:
        raise FactValidationError("identity_override")
    resolved_scope = param_scope or row_scope or SCOPE_SYMBOL
    row_subject = _bar_row_subject(row, scope=resolved_scope)
    if param_subject is not None and row_subject is not None:
        if normalize_subject(resolved_scope, param_subject) != normalize_subject(
            resolved_scope, row_subject
        ):
            raise FactValidationError("identity_override")
    resolved_subject = param_subject or row_subject
    return ValidatedBar(
        as_of=as_of_text,
        open=open_px,
        high=high,
        low=low,
        close=close,
        volume=volume,
        refs=refs or (),
        scope=resolved_scope,
        subject=resolved_subject,
        synthetic=bool(row.get("synthetic", True)),
    )


def require_valid_fact(
    *,
    metric: str,
    value: Any,
    as_of: str | None,
    unit: str | None = None,
    refs: tuple[FactRef, ...] | None = None,
    scope: str | None = None,
    subject: str | None = None,
    synthetic: bool = True,
) -> ValidatedFact:
    number = as_number(value)
    if number is None:
        raise FactValidationError(f"numeric fact {metric!r} is missing or non-finite")
    return ValidatedFact(
        metric=metric,
        value=number,
        as_of=as_of,
        unit=unit,
        refs=refs or (),
        scope=scope,
        subject=subject,
        synthetic=synthetic,
    )


def is_price_metric(metric: str) -> bool:
    return (metric or "").strip().lower() in PRICE_METRICS
