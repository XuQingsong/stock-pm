"""Expectation layer: actual vs latest pre-print consensus, plus revisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .numbers import as_number, pct_delta, round_pct
from .types import FactRef


ALLOWED_BASIS = {"gaap", "non-gaap", "non_gaap", "unknown"}


@dataclass(frozen=True)
class ExpectationPoint:
    value: float | None
    as_of: str | None
    source: str | None
    currency: str | None
    basis: str
    fact_ref: FactRef | None = None
    analyst_count: int | None = None
    synthetic: bool = True
    fiscal_period: str | None = None


@dataclass(frozen=True)
class ExpectationGap:
    id: str
    metric: str
    fiscal_period: str | None
    actual: float | None
    latest_consensus: float | None
    prior_consensus: float | None
    actual_as_of: str | None
    latest_consensus_as_of: str | None
    prior_consensus_as_of: str | None
    surprise_pct: float | None
    revision_pct: float | None
    revision_trend: str | None
    analyst_count: int | None
    currency: str | None
    basis: str | None
    status: str
    reason: str
    fact_refs: tuple[FactRef, ...]
    synthetic: bool = True

    def to_dict(self) -> dict[str, Any]:
        from .types import to_dict

        return to_dict(self)


def _basis(value: str | None) -> str:
    raw = (value or "unknown").strip().lower().replace(" ", "-")
    if raw in {"non-gaap", "non_gaap", "nongaap"}:
        return "non-gaap"
    if raw == "gaap":
        return "gaap"
    return "unknown"


def _compatible(left: ExpectationPoint | None, right: ExpectationPoint | None) -> str | None:
    if left is None or right is None:
        return None
    if left.currency and right.currency and left.currency != right.currency:
        return "currency_conflict"
    left_b, right_b = _basis(left.basis), _basis(right.basis)
    if left_b != "unknown" and right_b != "unknown" and left_b != right_b:
        return "basis_conflict"
    if (
        left.source
        and right.source
        and left.source != right.source
        and left.value is not None
        and right.value is not None
        and left.value != right.value
        and left_b != right_b
    ):
        return "source_conflict"
    return None


def _trend(revision_pct: float | None) -> str | None:
    if revision_pct is None:
        return None
    if revision_pct > 0:
        return "up"
    if revision_pct < 0:
        return "down"
    return "unchanged"


def parse_as_of(value: str | None) -> datetime | None | str:
    """Return datetime, None if missing, or 'invalid' if unparseable."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return "invalid"
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def _point_period(point: ExpectationPoint | None) -> str | None:
    if point is None:
        return None
    text = (point.fiscal_period or "").strip()
    return text or None


def _blocked_gap(
    *,
    ident: str,
    metric: str,
    fiscal_period: str | None,
    actual: ExpectationPoint | None,
    latest_consensus: ExpectationPoint | None,
    prior_consensus: ExpectationPoint | None,
    refs: tuple[FactRef, ...],
    status: str,
    reason: str,
    synthetic: bool,
) -> ExpectationGap:
    return ExpectationGap(
        id=ident,
        metric=metric,
        fiscal_period=fiscal_period,
        actual=as_number(actual.value) if actual else None,
        latest_consensus=as_number(latest_consensus.value) if latest_consensus else None,
        prior_consensus=as_number(prior_consensus.value) if prior_consensus else None,
        actual_as_of=actual.as_of if actual else None,
        latest_consensus_as_of=latest_consensus.as_of if latest_consensus else None,
        prior_consensus_as_of=prior_consensus.as_of if prior_consensus else None,
        surprise_pct=None,
        revision_pct=None,
        revision_trend=None,
        analyst_count=latest_consensus.analyst_count if latest_consensus else None,
        currency=None,
        basis=None,
        status=status,
        reason=reason,
        fact_refs=refs,
        synthetic=synthetic,
    )


def _validate_periods(
    fiscal_period: str | None,
    actual: ExpectationPoint | None,
    latest_consensus: ExpectationPoint | None,
    prior_consensus: ExpectationPoint | None,
) -> str | None:
    periods: list[str] = []
    gap_period = (fiscal_period or "").strip()
    if gap_period:
        periods.append(gap_period)
    for point in (actual, latest_consensus, prior_consensus):
        period = _point_period(point)
        if period:
            periods.append(period)
    if periods and len(set(periods)) > 1:
        return "不同 fiscal period 禁止比较"
    return None


def _validate_as_of_order(
    actual: ExpectationPoint | None,
    latest_consensus: ExpectationPoint | None,
    prior_consensus: ExpectationPoint | None,
) -> tuple[str, str] | None:
    parsed: dict[str, datetime] = {}
    for name, point in (
        ("prior", prior_consensus),
        ("latest", latest_consensus),
        ("actual", actual),
    ):
        if point is None:
            continue
        dt = parse_as_of(point.as_of)
        if dt is None:
            return ("insufficient", "缺失 as_of，不能比较预期")
        if dt == "invalid":
            return ("insufficient", "非法 as_of，不能比较预期")
        parsed[name] = dt
    if "prior" in parsed and "latest" in parsed and not (parsed["prior"] < parsed["latest"]):
        return ("conflict", "时间顺序颠倒：prior_as_of 必须早于 latest_as_of")
    if "latest" in parsed and "actual" in parsed and not (parsed["latest"] < parsed["actual"]):
        return ("conflict", "latest 必须是财报前共识（latest_as_of < actual_as_of）")
    if "prior" in parsed and "actual" in parsed and not (parsed["prior"] < parsed["actual"]):
        return ("conflict", "时间顺序颠倒：prior_as_of 必须早于 actual_as_of")
    return None


def build_expectation_gap(
    *,
    metric: str,
    fiscal_period: str | None,
    actual: ExpectationPoint | None = None,
    latest_consensus: ExpectationPoint | None = None,
    prior_consensus: ExpectationPoint | None = None,
    conflicting_latest: ExpectationPoint | None = None,
    gap_id: str | None = None,
    synthetic: bool = True,
) -> ExpectationGap:
    refs: list[FactRef] = []
    for point in (actual, latest_consensus, prior_consensus):
        if point and point.fact_ref:
            refs.append(point.fact_ref)

    ident = gap_id or f"exp|{metric}|{fiscal_period or ''}"
    ref_tuple = tuple(refs)

    period_reason = _validate_periods(fiscal_period, actual, latest_consensus, prior_consensus)
    if period_reason:
        return _blocked_gap(
            ident=ident,
            metric=metric,
            fiscal_period=fiscal_period,
            actual=actual,
            latest_consensus=latest_consensus,
            prior_consensus=prior_consensus,
            refs=ref_tuple,
            status="insufficient",
            reason=period_reason,
            synthetic=synthetic,
        )

    as_of_block = _validate_as_of_order(actual, latest_consensus, prior_consensus)
    if as_of_block:
        status, reason = as_of_block
        return _blocked_gap(
            ident=ident,
            metric=metric,
            fiscal_period=fiscal_period,
            actual=actual,
            latest_consensus=latest_consensus,
            prior_consensus=prior_consensus,
            refs=ref_tuple,
            status=status,
            reason=reason,
            synthetic=synthetic,
        )

    if conflicting_latest is not None and latest_consensus is not None:
        return _blocked_gap(
            ident=ident,
            metric=metric,
            fiscal_period=fiscal_period,
            actual=actual,
            latest_consensus=latest_consensus,
            prior_consensus=prior_consensus,
            refs=ref_tuple,
            status="conflict",
            reason="来源或口径冲突，不得任选一个共识",
            synthetic=synthetic,
        )

    for left, right in (
        (actual, latest_consensus),
        (latest_consensus, prior_consensus),
        (actual, prior_consensus),
    ):
        conflict = _compatible(left, right)
        if conflict:
            return _blocked_gap(
                ident=ident,
                metric=metric,
                fiscal_period=fiscal_period,
                actual=actual,
                latest_consensus=latest_consensus,
                prior_consensus=prior_consensus,
                refs=ref_tuple,
                status="conflict",
                reason="来源或口径冲突，不得任选一个共识",
                synthetic=synthetic,
            )

    actual_v = as_number(actual.value) if actual else None
    latest_v = as_number(latest_consensus.value) if latest_consensus else None
    prior_v = as_number(prior_consensus.value) if prior_consensus else None
    surprise = round_pct(pct_delta(actual_v, latest_v))
    revision = round_pct(pct_delta(latest_v, prior_v)) if prior_v is not None else None
    if prior_v is None:
        revision_trend = None
        reason = "缺历史共识，不能生成 revision trend"
        status = "ok" if latest_v is not None or actual_v is not None else "insufficient"
        if latest_v is None and actual_v is not None:
            status = "insufficient"
            reason = "缺最新财报前预期，actual 不能比较"
        elif prior_v is None:
            status = "ok" if latest_v is not None else "insufficient"
    else:
        revision_trend = _trend(revision)
        status = "ok"
        reason = "actual 对照最新财报前共识；修订对照更早共识"

    if actual_v is not None and latest_v is None:
        status = "insufficient"
        surprise = None
        reason = "缺最新财报前预期，actual 不能比较"

    currency = None
    basis = None
    for point in (actual, latest_consensus, prior_consensus):
        if point and point.currency:
            currency = point.currency
            break
    for point in (actual, latest_consensus, prior_consensus):
        if point:
            basis = _basis(point.basis)
            break

    return ExpectationGap(
        id=ident,
        metric=metric,
        fiscal_period=fiscal_period,
        actual=actual_v,
        latest_consensus=latest_v,
        prior_consensus=prior_v,
        actual_as_of=actual.as_of if actual else None,
        latest_consensus_as_of=latest_consensus.as_of if latest_consensus else None,
        prior_consensus_as_of=prior_consensus.as_of if prior_consensus else None,
        surprise_pct=surprise,
        revision_pct=revision,
        revision_trend=revision_trend,
        analyst_count=latest_consensus.analyst_count if latest_consensus else None,
        currency=currency,
        basis=basis,
        status=status,
        reason=reason,
        fact_refs=tuple(refs),
        synthetic=synthetic,
    )
