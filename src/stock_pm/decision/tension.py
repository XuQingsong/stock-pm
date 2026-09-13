"""Price vs expectation tension. Describes evidence; never priced_in."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .change import ChangeSnapshot
from .expectation import ExpectationGap
from .numbers import as_number, pct_delta, round_pct


@dataclass(frozen=True)
class PriceExpectationTension:
    fundamentals_change: float | None
    price_change: float | None
    valuation_change: float | None
    tension: str
    evidence_quality: str
    reason: str
    divergence_kind: str | None = None
    code: str = ""
    synthetic: bool = True

    def to_dict(self) -> dict[str, Any]:
        from .types import to_dict

        return to_dict(self)


def build_price_expectation_tension(
    *,
    fundamentals_change: float | ExpectationGap | ChangeSnapshot | None,
    price_change: float | ChangeSnapshot | None,
    valuation_change: float | ChangeSnapshot | None = None,
    synthetic: bool = True,
) -> PriceExpectationTension:
    fund = _as_pct(fundamentals_change, prefer_revision=True)
    price = _as_pct(price_change)
    valuation = _as_pct(valuation_change)
    if fund is None or price is None:
        return PriceExpectationTension(
            fundamentals_change=fund,
            price_change=price,
            valuation_change=valuation,
            tension="insufficient",
            evidence_quality="insufficient",
            reason="数据不足，只描述证据，不冒充已定价结论",
            divergence_kind=None,
            code="insufficient",
            synthetic=synthetic,
        )
    quality = "complete" if valuation is not None else "partial"
    if fund > 0 and price < 0:
        return PriceExpectationTension(
            fundamentals_change=fund,
            price_change=price,
            valuation_change=valuation,
            tension="divergence",
            evidence_quality=quality,
            reason="基本面改善而价格下跌，方向背离，不得用绝对值抹平符号",
            divergence_kind="fundamentals_up_price_down",
            code="fundamentals_up_price_down",
            synthetic=synthetic,
        )
    if fund < 0 and price > 0:
        return PriceExpectationTension(
            fundamentals_change=fund,
            price_change=price,
            valuation_change=valuation,
            tension="divergence",
            evidence_quality=quality,
            reason="基本面下修而价格上涨，方向背离，不得用绝对值抹平符号",
            divergence_kind="fundamentals_down_price_up",
            code="fundamentals_down_price_up",
            synthetic=synthetic,
        )
    abs_fund, abs_price = abs(fund), abs(price)
    both_negative = fund < 0 and price < 0
    valuation_expanded = valuation is not None and valuation > 0
    valuation_compressed = valuation is not None and valuation < 0
    if both_negative:
        if abs_price > abs_fund * 1.5:
            tension = "price_decline_ahead_of_fundamentals"
            reason = "价格跌幅明显快于基本面恶化"
            code = "price_decline_ahead"
        elif abs_fund > abs_price * 1.5:
            tension = "deteriorating_faster_than_price"
            reason = "基本面恶化快于价格下跌"
            code = "deteriorating_faster"
        else:
            tension = "aligned"
            reason = "基本面恶化与价格下跌量级接近"
            code = "aligned_down"
        return PriceExpectationTension(
            fundamentals_change=fund,
            price_change=price,
            valuation_change=valuation,
            tension=tension,
            evidence_quality=quality,
            reason=reason,
            divergence_kind=None,
            code=code,
            synthetic=synthetic,
        )
    if abs_price > abs_fund * 1.5 and (valuation_expanded or valuation is None):
        tension = "price_ahead_of_fundamentals"
        reason = "价格涨幅明显快于基本面修订，估值若扩张则更支持这一描述"
        code = "price_ahead"
    elif abs_fund > abs_price * 1.5 and (valuation_compressed or valuation is None or abs_price < abs_fund):
        tension = "improving_faster_than_price"
        reason = "基本面修订快于价格变动"
        code = "improving_faster"
    else:
        tension = "aligned"
        reason = "基本面修订与价格变动量级接近"
        code = "aligned_up"
    return PriceExpectationTension(
        fundamentals_change=fund,
        price_change=price,
        valuation_change=valuation,
        tension=tension,
        evidence_quality=quality,
        reason=reason,
        divergence_kind=None,
        code=code,
        synthetic=synthetic,
    )


def _as_pct(value: float | ExpectationGap | ChangeSnapshot | None, *, prefer_revision: bool = False) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round_pct(float(value))
    if isinstance(value, ExpectationGap):
        picked = value.revision_pct if prefer_revision else value.surprise_pct
        return round_pct(picked if picked is not None else value.revision_pct)
    if isinstance(value, ChangeSnapshot):
        if value.delta_pct is not None:
            return round_pct(value.delta_pct)
        return round_pct(pct_delta(value.current_value, value.previous_value))
    return as_number(value)
