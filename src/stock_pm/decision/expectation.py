"""Expectation layer: actual vs latest pre-print consensus, plus revisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .numbers import as_number, pct_delta, round_pct
from .timeparse import parse_as_of
from .types import (
    SCOPE_GLOBAL,
    FactRef,
    infer_scope,
    make_evidence_id,
    normalize_subject,
)


CONSENSUS_ABS_TOLERANCE = 0.01
CONSENSUS_REL_TOLERANCE = 0.005


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
    scope: str | None = None
    subject: str | None = None

    def __post_init__(self) -> None:
        scope = (self.scope or "").strip() or None
        if scope:
            object.__setattr__(self, "scope", scope)
            object.__setattr__(self, "subject", normalize_subject(scope, self.subject))
        elif self.subject is not None:
            object.__setattr__(self, "subject", str(self.subject).strip() or None)


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
    code: str = ""
    scope: str = SCOPE_GLOBAL
    subject: str | None = None
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


def _compatible_basis_currency(
    left: ExpectationPoint | None, right: ExpectationPoint | None
) -> str | None:
    if left is None or right is None:
        return None
    if left.currency and right.currency and left.currency != right.currency:
        return "currency_conflict"
    left_b, right_b = _basis(left.basis), _basis(right.basis)
    if left_b != "unknown" and right_b != "unknown" and left_b != right_b:
        return "basis_conflict"
    return None


def _values_diverge(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return False
    if abs(left - right) <= CONSENSUS_ABS_TOLERANCE:
        return False
    scale = max(abs(left), abs(right))
    if scale > 0 and abs(left - right) / scale <= CONSENSUS_REL_TOLERANCE:
        return False
    return True


def _same_consensus_snapshot(left: ExpectationPoint, right: ExpectationPoint, gap_period: str | None) -> bool:
    left_period = (left.fiscal_period or gap_period or "").strip()
    right_period = (right.fiscal_period or gap_period or "").strip()
    if left_period and right_period and left_period != right_period:
        return False
    left_dt = parse_as_of(left.as_of)
    right_dt = parse_as_of(right.as_of)
    if not isinstance(left_dt, datetime) or not isinstance(right_dt, datetime):
        return False
    if left_dt != right_dt:
        return False
    if _compatible_basis_currency(left, right):
        return False
    return True


def _trend(revision_pct: float | None) -> str | None:
    if revision_pct is None:
        return None
    if revision_pct > 0:
        return "up"
    if revision_pct < 0:
        return "down"
    return "unchanged"


def _point_period(point: ExpectationPoint | None) -> str | None:
    if point is None:
        return None
    text = (point.fiscal_period or "").strip()
    return text or None


def _point_identity(metric: str, point: ExpectationPoint | None) -> tuple[str, str] | None:
    if point is None:
        return None
    scope = infer_scope(metric, point.scope)
    subject = normalize_subject(scope, point.subject)
    if scope != SCOPE_GLOBAL and not subject:
        return scope, ""
    return scope, subject or "global"


def _resolve_gap_identity(
    metric: str,
    actual: ExpectationPoint | None,
    latest_consensus: ExpectationPoint | None,
    prior_consensus: ExpectationPoint | None,
    conflicting_latest: ExpectationPoint | None,
    scope: str | None,
    subject: str | None,
) -> tuple[str, str] | tuple[None, str]:
    identities: list[tuple[str, str]] = []
    for point in (actual, latest_consensus, prior_consensus, conflicting_latest):
        ident = _point_identity(metric, point)
        if ident is not None:
            identities.append(ident)
    if any(item[1] == "" for item in identities):
        return None, "missing_subject"
    unique = set(identities)
    if len(unique) > 1:
        return None, "subject_mismatch"
    if unique:
        derived_scope, derived_subject = next(iter(unique))
    else:
        derived_scope = infer_scope(metric, scope)
        derived_subject = normalize_subject(derived_scope, subject) or ("global" if derived_scope == SCOPE_GLOBAL else "")
        if derived_scope != SCOPE_GLOBAL and not derived_subject:
            return None, "missing_subject"
    if scope is not None and scope != derived_scope:
        return None, "identity_override"
    if subject is not None and normalize_subject(derived_scope, subject) != derived_subject:
        return None, "identity_override"
    return derived_scope, derived_subject


def _collect_refs(*points: ExpectationPoint | None) -> tuple[FactRef, ...]:
    refs: list[FactRef] = []
    seen: set[tuple] = set()
    for point in points:
        if not point or not point.fact_ref:
            continue
        ref = point.fact_ref
        key = (ref.ref_table, str(ref.ref_id), ref.as_of, ref.source)
        if key in seen:
            continue
        seen.add(key)
        refs.append(ref)
    return tuple(refs)


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
    code: str,
    scope: str,
    subject: str | None,
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
        code=code,
        scope=scope,
        subject=subject,
        synthetic=synthetic,
    )


def _resolved_period(
    fiscal_period: str | None,
    actual: ExpectationPoint | None,
    latest_consensus: ExpectationPoint | None,
    prior_consensus: ExpectationPoint | None,
    conflicting_latest: ExpectationPoint | None,
) -> tuple[str | None, str | None]:
    periods: list[str] = []
    gap_period = (fiscal_period or "").strip()
    if gap_period:
        periods.append(gap_period)
    for point in (actual, latest_consensus, prior_consensus, conflicting_latest):
        period = _point_period(point)
        if period:
            periods.append(period)
    unique = set(periods)
    if unique and len(unique) > 1:
        return None, "period_mismatch"
    if not unique:
        return None, "missing_period"
    return next(iter(unique)), None


def _validate_as_of_order(
    actual: ExpectationPoint | None,
    latest_consensus: ExpectationPoint | None,
    prior_consensus: ExpectationPoint | None,
) -> tuple[str, str, str] | None:
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
            return ("insufficient", "missing_as_of", "缺失 as_of，不能比较预期")
        if dt == "invalid":
            return ("insufficient", "invalid_as_of", "非法 as_of，不能比较预期")
        parsed[name] = dt
    if "prior" in parsed and "latest" in parsed and not (parsed["prior"] < parsed["latest"]):
        return ("conflict", "time_order", "时间顺序颠倒：prior_as_of 必须早于 latest_as_of")
    if "latest" in parsed and "actual" in parsed and not (parsed["latest"] < parsed["actual"]):
        return ("conflict", "time_order", "latest 必须是财报前共识（latest_as_of < actual_as_of）")
    if "prior" in parsed and "actual" in parsed and not (parsed["prior"] < parsed["actual"]):
        return ("conflict", "time_order", "时间顺序颠倒：prior_as_of 必须早于 actual_as_of")
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
    scope: str | None = None,
    subject: str | None = None,
    synthetic: bool = True,
) -> ExpectationGap:
    refs = _collect_refs(actual, latest_consensus, prior_consensus, conflicting_latest)
    identity = _resolve_gap_identity(
        metric, actual, latest_consensus, prior_consensus, conflicting_latest, scope, subject
    )
    if identity[0] is None:
        code = str(identity[1])
        ident = gap_id or f"exp|{metric}|{fiscal_period or ''}"
        reason = {
            "missing_subject": "symbol scope 缺 subject，不能比较",
            "subject_mismatch": "输入点 subject/scope 不一致，禁止比较",
            "identity_override": "禁止用 builder 参数覆盖输入证据身份",
        }.get(code, code)
        status = "conflict" if code in {"subject_mismatch", "identity_override"} else "insufficient"
        return _blocked_gap(
            ident=ident,
            metric=metric,
            fiscal_period=fiscal_period,
            actual=actual,
            latest_consensus=latest_consensus,
            prior_consensus=prior_consensus,
            refs=refs,
            status=status,
            reason=reason,
            code=code,
            scope=infer_scope(metric, scope),
            subject=subject,
            synthetic=synthetic,
        )
    derived_scope, derived_subject = identity
    ident = gap_id or make_evidence_id("exp", derived_scope, derived_subject, metric, fiscal_period or "")

    def blocked(status: str, code: str, reason: str) -> ExpectationGap:
        return _blocked_gap(
            ident=ident,
            metric=metric,
            fiscal_period=fiscal_period,
            actual=actual,
            latest_consensus=latest_consensus,
            prior_consensus=prior_consensus,
            refs=refs,
            status=status,
            reason=reason,
            code=code,
            scope=derived_scope,
            subject=derived_subject,
            synthetic=synthetic,
        )

    period, period_code = _resolved_period(
        fiscal_period, actual, latest_consensus, prior_consensus, conflicting_latest
    )
    if period_code == "period_mismatch":
        return blocked("insufficient", "period_mismatch", "不同 fiscal period 禁止比较")
    if period_code == "missing_period":
        return blocked("insufficient", "missing_period", "fiscal period 缺失，不能声称完整可比")

    as_of_block = _validate_as_of_order(actual, latest_consensus, prior_consensus)
    if as_of_block:
        status, code, reason = as_of_block
        return blocked(status, code, reason)

    if conflicting_latest is not None and latest_consensus is not None:
        if not _same_consensus_snapshot(latest_consensus, conflicting_latest, period):
            return blocked("conflict", "source_conflict", "多来源共识不是同一快照，不得任选")
        left_v = as_number(latest_consensus.value)
        right_v = as_number(conflicting_latest.value)
        if _values_diverge(left_v, right_v):
            return blocked("conflict", "source_conflict", "同一快照多来源共识差异超过容差，不得任选")

    for left, right in (
        (actual, latest_consensus),
        (latest_consensus, prior_consensus),
        (actual, prior_consensus),
    ):
        conflict = _compatible_basis_currency(left, right)
        if conflict:
            return blocked("conflict", conflict, "来源或口径冲突，不得任选一个共识")

    actual_v = as_number(actual.value) if actual else None
    latest_v = as_number(latest_consensus.value) if latest_consensus else None
    prior_v = as_number(prior_consensus.value) if prior_consensus else None
    surprise = round_pct(pct_delta(actual_v, latest_v))
    revision = round_pct(pct_delta(latest_v, prior_v)) if prior_v is not None and latest_v is not None else None
    can_surprise = actual_v is not None and latest_v is not None
    can_revision = latest_v is not None and prior_v is not None
    if latest_v is None:
        return blocked("insufficient", "missing_latest", "缺最新财报前预期，actual 不能比较")
    if not can_surprise and not can_revision:
        return blocked("insufficient", "insufficient_points", "缺比较点，不能生成完整预期差")

    if can_revision:
        revision_trend = _trend(revision)
        status = "ok"
        code = "ok"
        reason = "actual 对照最新财报前共识；修订对照更早共识"
        if not can_surprise:
            reason = "修订对照更早共识；缺 actual 故无 surprise"
    else:
        revision_trend = None
        revision = None
        status = "ok"
        code = "ok"
        reason = "缺历史共识，不能生成 revision trend"

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
        fiscal_period=period,
        actual=actual_v,
        latest_consensus=latest_v,
        prior_consensus=prior_v,
        actual_as_of=actual.as_of if actual else None,
        latest_consensus_as_of=latest_consensus.as_of if latest_consensus else None,
        prior_consensus_as_of=prior_consensus.as_of if prior_consensus else None,
        surprise_pct=surprise if can_surprise else None,
        revision_pct=revision,
        revision_trend=revision_trend,
        analyst_count=latest_consensus.analyst_count if latest_consensus else None,
        currency=currency,
        basis=basis,
        status=status,
        reason=reason,
        fact_refs=refs,
        code=code,
        scope=derived_scope,
        subject=derived_subject,
        synthetic=synthetic,
    )
