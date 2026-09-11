"""Causal impact: mechanism + exposure + market confirmation. No layer jumps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from stock_pm.impact import THEME_NAMES

from .change import ChangeSnapshot
from .types import FactRef


RATES_DISCOUNT_MECHANISM = "inflation_to_rates_to_discount"
OIL_PRODUCER_MECHANISM = "commodity_price_to_producer_revenue"
OIL_CONSUMER_MECHANISM = "commodity_price_to_input_cost"

CHANNEL_DURATION = "high_valuation_duration"
CHANNEL_COMMODITY_REVENUE = "commodity_revenue"
CHANNEL_FUEL_COST = "fuel_cost"

UNCONFIRMED = "市场未确认"
UNVERIFIED = "unverified"


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
    synthetic: bool = True

    def to_dict(self) -> dict[str, Any]:
        from .types import to_dict

        return to_dict(self)


def _tightening_sign(metric: str, direction: str) -> bool:
    if metric in {"us2y", "us_2y", "real_rate", "real_rates", "vix"}:
        return direction == "up"
    if metric in {"cut_odds", "rate_cut_odds", "cut_probability"}:
        return direction == "down"
    return False


def assess_market_confirmation(
    *,
    path: str,
    series: Iterable[ChangeSnapshot],
    synthetic: bool = True,
) -> MarketConfirmation:
    rows = tuple(series)
    if not rows:
        return MarketConfirmation(
            path=path,
            status="insufficient",
            reason="未提供市场确认序列",
            series=rows,
        )
    if path == "rates_tightening":
        confirming = [
            row
            for row in rows
            if row.materiality == "material" and _tightening_sign(row.metric, row.direction)
        ]
        needed = {"us2y", "us_2y", "real_rate", "real_rates", "cut_odds", "rate_cut_odds", "cut_probability"}
        material_needed = [row for row in confirming if row.metric in needed]
        if len(material_needed) >= 2:
            return MarketConfirmation(
                path=path,
                status="confirmed",
                reason="美债/实际利率/降息预期中至少两项沿紧缩方向且达到重要性阈值",
                series=rows,
            )
        return MarketConfirmation(
            path=path,
            status="unconfirmed",
            reason=UNCONFIRMED,
            series=rows,
        )
    return MarketConfirmation(
        path=path,
        status="insufficient",
        reason="未知确认路径",
        series=rows,
    )


def _direction_for(mechanism: str | None, exposure: Exposure | None, cause: ChangeSnapshot | None) -> str | None:
    if not mechanism or not exposure or cause is None:
        return None
    cause_up = cause.direction == "up"
    cause_down = cause.direction == "down"
    if mechanism == RATES_DISCOUNT_MECHANISM and exposure.channel == CHANNEL_DURATION:
        if cause_up:
            return "bearish"
        if cause_down:
            return "bullish"
        return None
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
    refs: list[FactRef] = []
    if cause:
        refs.extend(cause.fact_refs)
    confirmation = market_confirmation or MarketConfirmation(
        path="none", status="insufficient", reason="未评估市场确认", series=()
    )
    counters = tuple(counter_evidence or ())
    ident = impact_id or f"cau|{(cause.metric if cause else 'na')}|{(exposure.target if exposure else 'na')}"
    target = exposure.target if exposure else None

    if claim is not None and (not claim.verified or claim.source_class in {"social", "rumor", "unverified"}):
        return CausalImpact(
            id=ident,
            cause=cause,
            market_confirmation=confirmation,
            mechanism=None,
            exposure=exposure,
            effect_target=target,
            direction=None,
            horizon=None,
            counter_evidence=counters,
            confidence="none",
            fact_refs=tuple(refs),
            status=UNVERIFIED,
            reason="未确认新闻只能作为线索，不能形成有效 CausalImpact",
            chain=(),
            synthetic=synthetic,
        )

    if cause is None:
        return CausalImpact(
            id=ident,
            cause=None,
            market_confirmation=confirmation,
            mechanism=mechanism,
            exposure=exposure,
            effect_target=target,
            direction=None,
            horizon=None,
            counter_evidence=counters,
            confidence="none",
            fact_refs=tuple(refs),
            status="insufficient",
            reason="缺 cause fact/change",
            chain=(),
            synthetic=synthetic,
        )

    is_macro_rates = mechanism == RATES_DISCOUNT_MECHANISM
    if is_macro_rates and (mechanism is None or exposure is None):
        return CausalImpact(
            id=ident,
            cause=cause,
            market_confirmation=confirmation,
            mechanism=mechanism,
            exposure=exposure,
            effect_target=target,
            direction=None,
            horizon=None,
            counter_evidence=counters,
            confidence="none",
            fact_refs=tuple(refs),
            status="insufficient",
            reason="宏观事实不能直接跳到个股方向：需要传导机制和 exposure",
            chain=(),
            synthetic=synthetic,
        )
    if mechanism is None or exposure is None:
        return CausalImpact(
            id=ident,
            cause=cause,
            market_confirmation=confirmation,
            mechanism=mechanism,
            exposure=exposure,
            effect_target=target,
            direction=None,
            horizon=None,
            counter_evidence=counters,
            confidence="none",
            fact_refs=tuple(refs),
            status="insufficient",
            reason="必须同时存在传导机制和公司/行业 exposure",
            chain=(),
            synthetic=synthetic,
        )

    if exposure.channel == CHANNEL_DURATION and mechanism != RATES_DISCOUNT_MECHANISM:
        return CausalImpact(
            id=ident,
            cause=cause,
            market_confirmation=confirmation,
            mechanism=mechanism,
            exposure=exposure,
            effect_target=target,
            direction=None,
            horizon=None,
            counter_evidence=counters,
            confidence="low",
            fact_refs=tuple(refs),
            status="insufficient",
            reason="高估值科技只有利率通道得到确认时才允许负向",
            chain=(),
            synthetic=synthetic,
        )

    if is_macro_rates or exposure.channel == CHANNEL_DURATION:
        if confirmation.status != "confirmed":
            return CausalImpact(
                id=ident,
                cause=cause,
                market_confirmation=confirmation,
                mechanism=mechanism,
                exposure=exposure,
                effect_target=target,
                direction=None,
                horizon=None,
                counter_evidence=counters + (confirmation.reason,),
                confidence="low",
                fact_refs=tuple(refs),
                status="unconfirmed",
                reason=UNCONFIRMED,
                chain=(),
                synthetic=synthetic,
            )

    direction = _direction_for(mechanism, exposure, cause)
    if direction is None:
        return CausalImpact(
            id=ident,
            cause=cause,
            market_confirmation=confirmation,
            mechanism=mechanism,
            exposure=exposure,
            effect_target=target,
            direction=None,
            horizon=None,
            counter_evidence=counters,
            confidence="low",
            fact_refs=tuple(refs),
            status="insufficient",
            reason="机制与 exposure 无法形成方向",
            chain=(),
            synthetic=synthetic,
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
        confidence="medium",
        fact_refs=tuple(refs),
        status="valid",
        reason="机制、exposure 与市场确认齐备",
        chain=_chain(mechanism, exposure),
        synthetic=synthetic,
    )
