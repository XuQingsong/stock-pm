"""Expectation layer: actual vs latest pre-print consensus, plus revisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

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
    if conflicting_latest is not None and latest_consensus is not None:
        return ExpectationGap(
            id=ident,
            metric=metric,
            fiscal_period=fiscal_period,
            actual=as_number(actual.value) if actual else None,
            latest_consensus=None,
            prior_consensus=as_number(prior_consensus.value) if prior_consensus else None,
            actual_as_of=actual.as_of if actual else None,
            latest_consensus_as_of=None,
            prior_consensus_as_of=prior_consensus.as_of if prior_consensus else None,
            surprise_pct=None,
            revision_pct=None,
            revision_trend=None,
            analyst_count=None,
            currency=None,
            basis=None,
            status="conflict",
            reason="来源或口径冲突，不得任选一个共识",
            fact_refs=tuple(refs),
            synthetic=synthetic,
        )

    for left, right in (
        (actual, latest_consensus),
        (latest_consensus, prior_consensus),
        (actual, prior_consensus),
    ):
        conflict = _compatible(left, right)
        if conflict:
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
                status="conflict",
                reason="来源或口径冲突，不得任选一个共识",
                fact_refs=tuple(refs),
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
