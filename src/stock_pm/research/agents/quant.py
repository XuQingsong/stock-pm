from __future__ import annotations

from statistics import pstdev
from typing import Any

from ..extract import to_number
from ..templates import load_prompt
from ..types import AGENT_QUANT, TENSION_STATES, AgentInput, AgentOutput
from .base import BaseAgent


PROMPT_VERSION = "sprint3-quant-v1"


def _latest_reaction(pack: dict[str, Any]) -> dict[str, Any]:
    rows = list(pack.get("price_reaction_history") or [])
    return dict(rows[0]) if rows else {}


def _fund_change(pack: dict[str, Any]) -> float | None:
    profile = pack.get("company_profile") or {}
    value = to_number(profile.get("revenue_growth_yoy_pct"))
    if value is not None:
        return value
    earnings = list(pack.get("earnings_history") or [])
    if not earnings:
        return None
    latest = earnings[0]
    surprise = to_number(latest.get("revenue_surprise_pct"))
    if surprise is not None:
        return surprise
    return to_number(latest.get("eps_surprise_pct"))


def classify_tension(
    *,
    fund_change: float | None,
    price_1d: float | None,
    vs_spy_1d: float | None = None,
    vs_spy_5d: float | None = None,
) -> str:
    if fund_change is None or price_1d is None:
        return "unclear"
    relative = vs_spy_1d if vs_spy_1d is not None else price_1d
    five = vs_spy_5d
    if fund_change >= 2 and (price_1d <= -1 or (relative is not None and relative <= -2)):
        return "fundamentals_ahead"
    if fund_change > 0 and (price_1d >= 8 or (five is not None and five >= 6) or (relative is not None and relative >= 6)):
        return "price_ahead"
    if fund_change >= 0 and price_1d >= 0:
        return "aligned"
    if fund_change <= 0 and price_1d <= 0:
        return "aligned"
    if (fund_change > 0 and price_1d < 0) or (fund_change < 0 and price_1d > 0):
        return "fundamentals_ahead" if fund_change > 0 else "price_ahead"
    return "unclear"


def _valuation_bits(pack: dict[str, Any], reaction: dict[str, Any]) -> dict[str, Any]:
    profile = pack.get("company_profile") or {}
    last_close = to_number(profile.get("last_close"))
    eps = to_number(profile.get("eps_ttm"))
    pe = to_number(profile.get("pe_ttm"))
    if pe is None and last_close not in (None, 0) and eps not in (None, 0):
        pe = round(last_close / eps, 2)
    post_5d = to_number(reaction.get("post_5d_return_pct"))
    pe_after = None
    if pe is not None and post_5d is not None:
        pe_after = round(pe * (1 + post_5d / 100.0), 2)
    return {"pe_ttm": pe, "last_close": last_close, "eps_ttm": eps, "implied_pe_after_5d": pe_after}


def _window_vol(pack: dict[str, Any]) -> float | None:
    closes = []
    profile = pack.get("company_profile") or {}
    series = profile.get("recent_closes") or pack.get("recent_closes") or []
    for item in series:
        if isinstance(item, dict):
            price = to_number(item.get("close") or item.get("close_price"))
        else:
            price = to_number(item)
        if price is not None:
            closes.append(price)
    if len(closes) < 6:
        return None
    rets = []
    for idx in range(1, len(closes)):
        if closes[idx - 1] in (None, 0):
            continue
        rets.append(100.0 * (closes[idx] / closes[idx - 1] - 1.0))
    if len(rets) < 5:
        return None
    return round(float(pstdev(rets[-20:])), 2)


class QuantAgent(BaseAgent):
    name = AGENT_QUANT
    prompt_version = PROMPT_VERSION

    def __init__(self, completer=None) -> None:
        super().__init__(completer=None, system_prompt=load_prompt("quant.txt"))

    def observe(self, payload: AgentInput) -> AgentOutput:
        pack = payload.research_pack or {}
        reaction = _latest_reaction(pack)
        findings: list[str] = []
        evidence: list[dict[str, Any]] = []
        missing: list[str] = list(pack.get("missing_fields") or [])
        fund_change = _fund_change(pack)
        price_1d = to_number(reaction.get("post_1d_return_pct") or reaction.get("day_return_pct"))
        vs_spy = to_number(reaction.get("vs_spy_1d_pct"))
        vs_qqq = to_number(reaction.get("vs_qqq_1d_pct"))
        vs_sector = to_number(reaction.get("vs_sector_1d_pct"))
        vs_spy_5d = to_number(reaction.get("vs_spy_5d_pct"))
        tension = classify_tension(
            fund_change=fund_change,
            price_1d=price_1d,
            vs_spy_1d=vs_spy,
            vs_spy_5d=vs_spy_5d,
        )
        if tension not in TENSION_STATES:
            tension = "unclear"
        stamp = reaction.get("report_date") or (pack.get("earnings_history") or [{}])[0].get("report_date")
        source = "daily_price_bars"
        if reaction:
            bits = [
                f"print={reaction.get('fiscal_period') or reaction.get('report_date')}",
                f"day={reaction.get('day_return_pct')}",
                f"post_1d={reaction.get('post_1d_return_pct')}",
                f"post_5d={reaction.get('post_5d_return_pct')}",
                f"vs_spy_1d={vs_spy}",
                f"vs_qqq_1d={vs_qqq}",
                f"vs_sector_1d={vs_sector}",
            ]
            if reaction.get("volume_vs_20d_avg") is not None:
                bits.append(f"volume_vs_20d={reaction.get('volume_vs_20d_avg')}")
            fact = "Earnings-window returns: " + ", ".join(str(item) for item in bits if not str(item).endswith("=None"))
            findings.append(fact)
            if stamp:
                evidence.append(
                    {
                        "_key": "q-reaction",
                        "evidence_type": "quant",
                        "fact": fact,
                        "excerpt": fact,
                        "source": source,
                        "source_time": stamp,
                        "source_type": "structured_provider",
                        "confidence": 0.7,
                        "raw_reference": dict(reaction),
                    }
                )
        else:
            findings.append("no earnings-window price reaction series in the research pack")
            if "price_reaction_history" not in missing:
                missing.append("price_reaction_history")

        if vs_spy is not None:
            findings.append(f"latest print versus SPY 1d is {vs_spy}%")
        if vs_qqq is not None:
            findings.append(f"latest print versus QQQ 1d is {vs_qqq}%")
        if vs_sector is not None:
            findings.append(f"latest print versus sector ETF 1d is {vs_sector}%")
        elif pack.get("benchmark_etf"):
            findings.append(f"sector ETF {pack.get('benchmark_etf')} relative return is unavailable")
            missing.append("vs_sector")

        valuation = _valuation_bits(pack, reaction)
        if valuation.get("pe_ttm") is not None:
            fact = f"TTM PE is {valuation['pe_ttm']}"
            if valuation.get("implied_pe_after_5d") is not None:
                fact += f"; 5d price move implies PE {valuation['implied_pe_after_5d']} if EPS is unchanged"
            findings.append(fact)
            if stamp:
                evidence.append(
                    {
                        "_key": "q-valuation",
                        "evidence_type": "quant",
                        "fact": fact,
                        "excerpt": fact,
                        "source": source,
                        "source_time": stamp,
                        "source_type": "structured_provider",
                        "confidence": 0.55,
                        "raw_reference": valuation,
                    }
                )
        else:
            missing.append("valuation_inputs")

        vol = to_number(reaction.get("pre_20d_realized_vol")) or _window_vol(pack)
        if vol is not None:
            findings.append(f"recent realized volatility of daily returns is {vol}%")

        findings.append(f"fundamentals-versus-price tension is {tension}")
        if fund_change is not None:
            findings.append(f"fundamental change used for tension is {fund_change}")
        if tension == "unclear":
            findings.append("price and fundamental series are incomplete or mixed, so tension stays unclear")

        assumption_links = []
        proposals = []
        for assumption in payload.assumptions:
            assumption_id = str(assumption.get("id") or "")
            if not assumption_id or not evidence:
                continue
            category = str(assumption.get("category") or "")
            direction = "contextual"
            if category == "valuation" and tension == "price_ahead":
                direction = "oppose"
            elif category in {"demand", "guidance_delivery"} and tension == "fundamentals_ahead":
                direction = "contextual"
            assumption_links.append(
                {
                    "assumption_id": assumption_id,
                    "evidence_key": evidence[0].get("_key"),
                    "direction": direction,
                    "strength": "moderate" if direction == "oppose" else "weak",
                    "reason": f"market tension={tension}; this is not an investment conclusion",
                }
            )
            proposed = "unchanged"
            reason = f"quant pass records tension={tension} without changing assumption status"
            if category == "valuation" and tension == "price_ahead":
                proposed = "weaken"
                reason = "price moved ahead of the fundamental change used for this window; valuation risk rose"
            proposals.append(
                {
                    "assumption_id": assumption_id,
                    "statement": assumption.get("statement"),
                    "proposed_status": proposed,
                    "reason": reason,
                    "confidence": 0.5,
                    "unresolved_gaps": [item for item in missing if item in {"price_reaction_history", "valuation_inputs", "vs_sector"}],
                }
            )

        missing_data = [
            item
            for item in dict.fromkeys(missing)
            if item in {"price_reaction_history", "valuation_inputs", "vs_sector"}
        ]
        confidence = 0.25
        if reaction:
            confidence = 0.55
        if vs_spy is not None or vs_sector is not None:
            confidence = min(0.75, confidence + 0.1)
        return AgentOutput(
            findings=findings,
            new_evidence=evidence,
            assumption_links=assumption_links,
            proposed_assumption_changes=proposals,
            missing_data=missing_data,
            confidence=confidence,
            agent_name=self.name,
            prompt_version=self.prompt_version,
        )
