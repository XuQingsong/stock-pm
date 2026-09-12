"""Selective industry/company exposure. No mechanical copy across names."""

from __future__ import annotations

from typing import Any

from stock_pm.config import DEFAULT_WATCHLIST

from .types import TrustedEvent


WATCH_EXPOSURE = {
    "NVDA": {
        "themes": ("semis", "high_valuation_growth"),
        "channels": ("risk_premium", "supply_chain"),
        "rate_sensitivity": "high",
    },
    "AAPL": {
        "themes": ("consumer_electronics",),
        "channels": ("demand",),
        "rate_sensitivity": "medium",
    },
    "XOM": {
        "themes": ("energy", "oil_producer"),
        "channels": ("commodity_revenue",),
        "rate_sensitivity": "low",
    },
    "JPM": {
        "themes": ("banks", "credit"),
        "channels": ("risk_premium", "credit_conditions"),
        "rate_sensitivity": "medium",
    },
}


def _seed(symbol: str) -> dict[str, Any]:
    extra = WATCH_EXPOSURE.get(symbol.upper(), {})
    row = DEFAULT_WATCHLIST.get(symbol.upper())
    themes = list(extra.get("themes") or ())
    if row:
        themes = list(row.themes) + themes
    return {
        "symbol": symbol.upper(),
        "themes": tuple(dict.fromkeys(themes)),
        "channels": extra.get("channels") or (),
        "rate_sensitivity": extra.get("rate_sensitivity") or (row.rate_sensitivity if row else "medium"),
    }


def why_relevant(event: TrustedEvent, symbol: str) -> dict[str, Any] | None:
    seed = _seed(symbol)
    event_type = event.event_type
    if event_type in {"war_sanctions", "energy_supply", "gold_wti"}:
        if "oil_producer" in seed["themes"] or "commodity_revenue" in seed["channels"]:
            return {
                "relevant": True,
                "channel": "commodity_revenue",
                "mechanism": "commodity_price_to_producer_revenue",
                "why_relevant": "原油生产收入直接暴露于供应中断/制裁带来的油价变化，不是把战争标题抄到所有股票",
            }
        if "high_valuation_growth" in seed["themes"] or "semis" in seed["themes"]:
            return {
                "relevant": True,
                "channel": "risk_premium",
                "mechanism": "geopolitical_risk_premium_to_duration",
                "why_relevant": "高估值成长/半导体通过风险溢价和供应链间接暴露，不是油企收入路径",
            }
        if "banks" in seed["themes"] or "credit" in seed["themes"]:
            return {
                "relevant": True,
                "channel": "risk_premium",
                "mechanism": "risk_premium_to_credit_conditions",
                "why_relevant": "银行通过风险溢价和信用条件暴露，不是油价收入",
            }
        return None
    if event_type in {"central_bank_rates", "inflation_employment"}:
        if seed["rate_sensitivity"] == "high" or "high_valuation_growth" in seed["themes"]:
            return {
                "relevant": True,
                "channel": "duration",
                "mechanism": "inflation_to_rates_to_discount",
                "why_relevant": "高利率敏感/久期暴露，利率贴现链进入该股观察，不是把宏观标题抄到所有股票",
            }
        if "banks" in seed["themes"] or "credit" in seed["themes"]:
            return {
                "relevant": True,
                "channel": "credit_conditions",
                "mechanism": "inflation_to_rates_to_credit",
                "why_relevant": "银行通过利率和信用条件暴露于通胀/就业事实，不是消费者电子路径",
            }
        return None
    if event_type == "vix_risk":
        # Market-center only. VIX confirms risk; it is not copied onto every stock card.
        return None
    if event_type == "company_filing" and symbol.upper() in {item.upper() for item in event.entities}:
        return {
            "relevant": True,
            "channel": "company",
            "mechanism": "company_filing",
            "why_relevant": "公司原文公告直接对应本标的",
        }
    return None


def attach_exposures(event: TrustedEvent, symbols: list[str]) -> list[dict[str, Any]]:
    rows = []
    for symbol in symbols:
        hit = why_relevant(event, symbol)
        if not hit:
            continue
        rows.append({"symbol": symbol.upper(), **hit})
    return rows
