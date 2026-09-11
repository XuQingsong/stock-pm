"""Causal impact: mechanism + exposure + market confirmation. No layer jumps."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Iterable

from stock_pm.impact import THEME_NAMES

from .change import ChangeSnapshot
from .timeparse import as_of_span, parse_as_of
from .types import FactRef, FactValidationError, has_provenance, make_evidence_id


RATES_DISCOUNT_MECHANISM = "inflation_to_rates_to_discount"
OIL_PRODUCER_MECHANISM = "commodity_price_to_producer_revenue"
OIL_CONSUMER_MECHANISM = "commodity_price_to_input_cost"

CHANNEL_DURATION = "high_valuation_duration"
CHANNEL_COMMODITY_REVENUE = "commodity_revenue"
CHANNEL_FUEL_COST = "fuel_cost"

UNCONFIRMED = "市场未确认"
UNVERIFIED = "unverified"
CONFIRMATION_AS_OF_TOLERANCE = timedelta(days=3)

METRIC_ALIASES = {
    "us_2y": "us2y",
    "ust2y": "us2y",
    "us2y": "us2y",
    "real_rates": "real_rate",
    "real_rate": "real_rate",
    "cut_odds": "cut_odds",
    "rate_cut_odds": "cut_odds",
    "cut_probability": "cut_odds",
    "fed_cut_odds": "cut_odds",
    "wti_crude": "wti",
    "wti": "wti",
    "brent": "brent",
    "oil": "oil",
    "crude": "oil",
    "cpi": "cpi",
    "core_cpi": "core_cpi",
    "pce": "pce",
    "core_pce": "core_pce",
    "inflation": "inflation",
}

RATES_CONFIRM_METRICS = frozenset({"us2y", "real_rate", "cut_odds"})
INFLATION_CAUSE_METRICS = frozenset({"cpi", "core_cpi", "pce", "core_pce", "inflation"})
OIL_CAUSE_METRICS = frozenset({"wti", "brent", "oil"})

MECHANISM_CAUSE_METRICS = {
    RATES_DISCOUNT_MECHANISM: INFLATION_CAUSE_METRICS,
    OIL_PRODUCER_MECHANISM: OIL_CAUSE_METRICS,
    OIL_CONSUMER_MECHANISM: OIL_CAUSE_METRICS,
}

MECHANISM_CONFIRM_PATH = {
    RATES_DISCOUNT_MECHANISM: "rates_tightening",
}

# Explicit contract: these mechanisms may not skip Expectation / Tension.
# Oil price → producer/consumer cash flow does not need a rate-path expectation.
# inflation_to_rates_to_discount is not an exception — it requires a traceable
# rate-path / cut-odds expectation delta before it can be a directional driver.
MECHANISMS_REQUIRING_EXPECTATION = frozenset({RATES_DISCOUNT_MECHANISM})
MECHANISMS_WITHOUT_EXPECTATION = frozenset({OIL_PRODUCER_MECHANISM, OIL_CONSUMER_MECHANISM})
RATE_PATH_EXPECTATION_METRICS = frozenset({"cut_odds", "us2y", "real_rate", "fed_funds", "rate_path"})


def mechanism_requires_expectation(mechanism: str | None) -> bool:
    return (mechanism or "") in MECHANISMS_REQUIRING_EXPECTATION


def canonical_metric(metric: str | None) -> str:
    raw = (metric or "").strip().lower()
    return METRIC_ALIASES.get(raw, raw)


def _tightening_sign(metric: str, direction: str) -> bool:
    key = canonical_metric(metric)
    if key in {"us2y", "real_rate", "vix"}:
        return direction == "up"
    if key == "cut_odds":
        return direction == "down"
    return False


@dataclass(frozen=True)
class Exposure:
    target: str
    target_kind: str
    channel: str
    theme: str | None = None


@dataclass(frozen=True)
class ClaimSource:
    source_class: str
    verified: bool
    text: str | None = None


@dataclass(frozen=True)
class MarketConfirmation:
    path: str
    status: str
    reason: str
    series: tuple[ChangeSnapshot, ...] = ()
    channels: tuple[str, ...] = ()
    used: tuple[ChangeSnapshot, ...] = ()
    code: str = ""

    def __post_init__(self) -> None:
        if self.status != "confirmed":
            return
        error = rates_confirmation_error(self.path, self.used)
        if error:
            raise FactValidationError(f"MarketConfirmation confirmed is invalid: {error}")


@dataclass(frozen=True)
class CausalImpact:
    id: str
    cause: ChangeSnapshot | None
    market_confirmation: MarketConfirmation
    mechanism: str | None
    exposure: Exposure | None
    effect_target: str | None
    direction: str | None
    horizon: str | None
    counter_evidence: tuple[str, ...]
    confidence: str
    fact_refs: tuple[FactRef, ...]
    status: str
    reason: str
    chain: tuple[str, ...]
    code: str = ""
    synthetic: bool = True

    def to_dict(self) -> dict[str, Any]:
        from .types import to_dict

        return to_dict(self)


def _dedupe_series(rows: tuple[ChangeSnapshot, ...]) -> tuple[ChangeSnapshot, ...]:
    seen: dict[str, ChangeSnapshot] = {}
    ordered: list[ChangeSnapshot] = []
    for row in rows:
        key = canonical_metric(row.metric)
        if key in seen:
            continue
        seen[key] = row
        ordered.append(row)
    return tuple(ordered)


def _windows_consistent(rows: Iterable[ChangeSnapshot]) -> bool:
    windows = {row.comparison_window for row in rows}
    return len(windows) <= 1


def _has_as_of(row: ChangeSnapshot) -> bool:
    dt = parse_as_of(row.current_as_of)
    return dt is not None and dt != "invalid"


def _as_of_cluster_ok(rows: Iterable[ChangeSnapshot], cause: ChangeSnapshot | None = None) -> bool:
    rows = tuple(rows)
    if not rows:
        return False
    stamps = [row.current_as_of for row in rows]
    if cause is not None:
        stamps.append(cause.current_as_of)
    span = as_of_span(stamps)
    if span is None:
        return False
    return span <= CONFIRMATION_AS_OF_TOLERANCE


def rates_confirmation_error(path: str, used: Iterable[ChangeSnapshot]) -> str | None:
    if path != "rates_tightening":
        return "forged_confirmation"
    rows = tuple(used)
    if not rows:
        return "forged_confirmation"
    channels = [canonical_metric(row.metric) for row in rows]
    if len(channels) != len(set(channels)):
        return "duplicate_channel"
    if len(set(channels)) < 2:
        return "forged_confirmation"
    if any(canonical_metric(row.metric) not in RATES_CONFIRM_METRICS for row in rows):
        return "forged_confirmation"
    if any(row.materiality != "material" for row in rows):
        return "forged_confirmation"
    if any(not _tightening_sign(row.metric, row.direction) for row in rows):
        return "confirmation_direction"
    if any(not has_provenance(row.fact_refs) for row in rows):
        return "missing_provenance"
    if any(not _has_as_of(row) for row in rows):
        return "missing_as_of"
    if not _windows_consistent(rows):
        return "window_mismatch"
    if not _as_of_cluster_ok(rows):
        return "as_of_mismatch"
    return None


def assess_market_confirmation(
    *,
    path: str,
    series: Iterable[ChangeSnapshot],
    synthetic: bool = True,
) -> MarketConfirmation:
    rows = tuple(series)
    unique = _dedupe_series(rows)
    if not rows:
        return MarketConfirmation(
            path=path,
            status="insufficient",
            reason="未提供市场确认序列",
            series=rows,
            channels=(),
            used=(),
            code="missing_series",
        )
    if path == "rates_tightening":
        confirming = [
            row
            for row in unique
            if row.materiality == "material" and _tightening_sign(row.metric, row.direction)
        ]
        needed = [
            row
            for row in confirming
            if canonical_metric(row.metric) in RATES_CONFIRM_METRICS and has_provenance(row.fact_refs)
        ]
        if any(not _has_as_of(row) for row in needed):
            return MarketConfirmation(
                path=path,
                status="unconfirmed",
                reason=UNCONFIRMED,
                series=rows,
                channels=tuple(canonical_metric(row.metric) for row in needed),
                used=(),
                code="missing_as_of",
            )
        if not _windows_consistent(needed):
            return MarketConfirmation(
                path=path,
                status="unconfirmed",
                reason="确认序列时间窗口不一致",
                series=rows,
                channels=tuple(canonical_metric(row.metric) for row in needed),
                used=(),
                code="window_mismatch",
            )
        if needed and not _as_of_cluster_ok(needed):
            return MarketConfirmation(
                path=path,
                status="unconfirmed",
                reason=UNCONFIRMED,
                series=rows,
                channels=tuple(canonical_metric(row.metric) for row in needed),
                used=(),
                code="as_of_mismatch",
            )
        channels = tuple(canonical_metric(row.metric) for row in needed)
        if len(set(channels)) >= 2:
            return MarketConfirmation(
                path=path,
                status="confirmed",
                reason="美债/实际利率/降息预期中至少两项独立通道沿紧缩方向且达到重要性阈值",
                series=rows,
                channels=tuple(dict.fromkeys(channels)),
                used=tuple(needed),
                code="confirmed",
            )
        return MarketConfirmation(
            path=path,
            status="unconfirmed",
            reason=UNCONFIRMED,
            series=rows,
            channels=tuple(dict.fromkeys(channels)),
            used=(),
            code="unconfirmed",
        )
    return MarketConfirmation(
        path=path,
        status="insufficient",
        reason="未知确认路径",
        series=rows,
        channels=tuple(canonical_metric(row.metric) for row in unique),
        used=(),
        code="unknown_path",
    )


def _mechanism_compatible(mechanism: str | None, cause: ChangeSnapshot | None) -> bool:
    if not mechanism or cause is None:
        return False
    allowed = MECHANISM_CAUSE_METRICS.get(mechanism)
    if not allowed:
        return False
    return canonical_metric(cause.metric) in allowed


def _direction_for(
    mechanism: str | None,
    exposure: Exposure | None,
    cause: ChangeSnapshot | None,
    confirmation: MarketConfirmation,
) -> str | None:
    if not mechanism or not exposure or cause is None:
        return None
    if mechanism == RATES_DISCOUNT_MECHANISM and exposure.channel == CHANNEL_DURATION:
        if confirmation.path == "rates_tightening" and confirmation.status == "confirmed":
            return "bearish"
        return None
    cause_up = cause.direction == "up"
    cause_down = cause.direction == "down"
    if mechanism == OIL_PRODUCER_MECHANISM and exposure.channel == CHANNEL_COMMODITY_REVENUE:
        if cause_up:
            return "bullish"
        if cause_down:
            return "bearish"
        return None
    if mechanism == OIL_CONSUMER_MECHANISM and exposure.channel == CHANNEL_FUEL_COST:
        if cause_up:
            return "bearish"
        if cause_down:
            return "bullish"
        return None
    return None


def _chain(mechanism: str | None, exposure: Exposure | None) -> tuple[str, ...]:
    if mechanism == RATES_DISCOUNT_MECHANISM:
        theme = THEME_NAMES.get(exposure.theme or "high_valuation_growth", "高估值股票") if exposure else "高估值股票"
        return ("通胀", "利率路径", "折现率", f"{theme}短期承压")
    if mechanism == OIL_PRODUCER_MECHANISM:
        return ("原油", "生产者收入", "能源生产商")
    if mechanism == OIL_CONSUMER_MECHANISM:
        return ("原油", "燃油成本", "航空公司")
    return ()


def _windows_match_cause(cause: ChangeSnapshot, confirmation: MarketConfirmation) -> bool:
    used = confirmation.used or ()
    if not used:
        return True
    if not _windows_consistent(used):
        return False
    series_window = used[0].comparison_window
    if cause.comparison_window is None or series_window is None:
        return True
    return cause.comparison_window == series_window


def _merge_fact_refs(cause: ChangeSnapshot | None, confirmation: MarketConfirmation) -> tuple[FactRef, ...]:
    refs: list[FactRef] = []
    seen: set[tuple] = set()

    def add(ref: FactRef) -> None:
        key = (ref.ref_table, str(ref.ref_id), ref.as_of, ref.source)
        if key in seen:
            return
        seen.add(key)
        refs.append(ref)

    if cause:
        for ref in cause.fact_refs:
            add(ref)
    for row in confirmation.used:
        for ref in row.fact_refs:
            add(ref)
    return tuple(refs)


def _impact(
    *,
    ident: str,
    cause: ChangeSnapshot | None,
    confirmation: MarketConfirmation,
    mechanism: str | None,
    exposure: Exposure | None,
    target: str | None,
    direction: str | None,
    horizon: str | None,
    counters: tuple[str, ...],
    confidence: str,
    status: str,
    reason: str,
    chain: tuple[str, ...],
    code: str,
    include_confirmation_refs: bool,
    synthetic: bool,
) -> CausalImpact:
    refs = _merge_fact_refs(cause, confirmation) if include_confirmation_refs else (
        tuple(cause.fact_refs) if cause else ()
    )
    return CausalImpact(
        id=ident,
        cause=cause,
        market_confirmation=confirmation,
        mechanism=mechanism,
        exposure=exposure,
        effect_target=target,
        direction=direction,
        horizon=horizon,
        counter_evidence=counters,
        confidence=confidence,
        fact_refs=refs,
        status=status,
        reason=reason,
        chain=chain,
        code=code,
        synthetic=synthetic,
    )


def build_causal_impact(
    *,
    cause: ChangeSnapshot | None,
    mechanism: str | None,
    exposure: Exposure | None,
    market_confirmation: MarketConfirmation | None,
    claim: ClaimSource | None = None,
    horizon: str | None = "short",
    counter_evidence: Iterable[str] | None = None,
    impact_id: str | None = None,
    synthetic: bool = True,
) -> CausalImpact:
    confirmation = market_confirmation or MarketConfirmation(
        path="none", status="insufficient", reason="未评估市场确认", series=(), code="missing_confirmation"
    )
    counters = tuple(counter_evidence or ())
    target = exposure.target if exposure else None
    ident = impact_id or make_evidence_id(
        "cau",
        cause.scope if cause else "na",
        cause.subject if cause else "na",
        cause.metric if cause else "na",
        target or "na",
    )

    def result(**kwargs: Any) -> CausalImpact:
        return _impact(
            ident=ident,
            cause=cause,
            confirmation=confirmation,
            exposure=exposure,
            target=target,
            counters=counters,
            synthetic=synthetic,
            include_confirmation_refs=False,
            **kwargs,
        )

    if claim is not None and (not claim.verified or claim.source_class in {"social", "rumor", "unverified"}):
        return result(
            mechanism=None,
            direction=None,
            horizon=None,
            confidence="none",
            status=UNVERIFIED,
            reason="未确认新闻只能作为线索，不能形成有效 CausalImpact",
            chain=(),
            code="unverified",
        )

    if cause is None:
        return result(
            mechanism=mechanism,
            direction=None,
            horizon=None,
            confidence="none",
            status="insufficient",
            reason="缺 cause fact/change",
            chain=(),
            code="missing_cause",
        )

    is_macro_rates = mechanism == RATES_DISCOUNT_MECHANISM
    if is_macro_rates and (mechanism is None or exposure is None):
        return result(
            mechanism=mechanism,
            direction=None,
            horizon=None,
            confidence="none",
            status="insufficient",
            reason="宏观事实不能直接跳到个股方向：需要传导机制和 exposure",
            chain=(),
            code="missing_mechanism",
        )
    if mechanism is None or exposure is None:
        return result(
            mechanism=mechanism,
            direction=None,
            horizon=None,
            confidence="none",
            status="insufficient",
            reason="必须同时存在传导机制和公司/行业 exposure",
            chain=(),
            code="missing_mechanism",
        )

    if not _mechanism_compatible(mechanism, cause):
        return result(
            mechanism=mechanism,
            direction=None,
            horizon=None,
            confidence="none",
            status="insufficient",
            reason="机制与原因指标不兼容",
            chain=(),
            code="mechanism_mismatch",
        )

    expected_path = MECHANISM_CONFIRM_PATH.get(mechanism)
    if expected_path and confirmation.path not in {expected_path, "none"} and confirmation.path:
        if confirmation.path != expected_path:
            return result(
                mechanism=mechanism,
                direction=None,
                horizon=None,
                confidence="low",
                status="insufficient",
                reason="确认路径与机制不兼容",
                chain=(),
                code="path_mismatch",
            )

    if exposure.channel == CHANNEL_DURATION and mechanism != RATES_DISCOUNT_MECHANISM:
        return result(
            mechanism=mechanism,
            direction=None,
            horizon=None,
            confidence="low",
            status="insufficient",
            reason="高估值科技只有利率通道得到确认时才允许负向",
            chain=(),
            code="channel_mismatch",
        )

    if is_macro_rates or exposure.channel == CHANNEL_DURATION:
        if confirmation.status == "confirmed":
            used_error = rates_confirmation_error(confirmation.path, confirmation.used)
            if used_error:
                return result(
                    mechanism=mechanism,
                    direction=None,
                    horizon=None,
                    confidence="low",
                    status="unconfirmed",
                    reason=UNCONFIRMED,
                    chain=(),
                    code=used_error,
                )
        else:
            return result(
                mechanism=mechanism,
                direction=None,
                horizon=None,
                confidence="low",
                status="unconfirmed",
                reason=UNCONFIRMED,
                chain=(),
                code="unconfirmed",
            )
        if not _windows_match_cause(cause, confirmation):
            return result(
                mechanism=mechanism,
                direction=None,
                horizon=None,
                confidence="low",
                status="unconfirmed",
                reason="确认序列与原因的时间窗口不一致",
                chain=(),
                code="window_mismatch",
            )
        if not _as_of_cluster_ok(confirmation.used, cause):
            return result(
                mechanism=mechanism,
                direction=None,
                horizon=None,
                confidence="low",
                status="unconfirmed",
                reason=UNCONFIRMED,
                chain=(),
                code="as_of_mismatch",
            )

    if cause.materiality != "material":
        return result(
            mechanism=mechanism,
            direction=None,
            horizon=None,
            confidence="low",
            status="insufficient",
            reason="原因变化未达重大阈值，不得形成 valid CausalImpact",
            chain=(),
            code="immaterial_cause",
        )

    if not has_provenance(cause.fact_refs):
        return result(
            mechanism=mechanism,
            direction=None,
            horizon=None,
            confidence="low",
            status="insufficient",
            reason="cause 缺少可追溯 FactRef，不得形成 valid CausalImpact",
            chain=(),
            code="missing_provenance",
        )

    direction = _direction_for(mechanism, exposure, cause, confirmation)
    if direction is None:
        return result(
            mechanism=mechanism,
            direction=None,
            horizon=None,
            confidence="low",
            status="insufficient",
            reason="机制、确认路径与 exposure 无法形成方向",
            chain=(),
            code="no_direction",
        )

    return _impact(
        ident=ident,
        cause=cause,
        confirmation=confirmation,
        mechanism=mechanism,
        exposure=exposure,
        target=target,
        direction=direction,
        horizon=horizon,
        counters=counters,
        confidence="medium",
        status="valid",
        reason="机制、exposure 与市场确认齐备",
        chain=_chain(mechanism, exposure),
        code="valid",
        include_confirmation_refs=True,
        synthetic=synthetic,
    )
