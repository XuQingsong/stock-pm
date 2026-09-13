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

ENERGY_MARKERS = {"oil", "crude", "wti", "energy", "opec", "brent", "gasoline"}
SEMIS_MARKERS = {"semis", "semiconductor", "export", "bis", "gpu", "chip", "nvda", "nvidia"}
CREDIT_MARKERS = {"credit", "bank", "debt", "default", "cds", "loan"}


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


def _tokens(event: TrustedEvent) -> set[str]:
    # Do not tokenize event_type: "central_bank_rates" would inject a false "bank" token.
    parts = list(event.entities) + list(event.countries) + [event.canonical_title]
    blob = " ".join(str(item) for item in parts).lower()
    return {item for item in blob.replace("/", " ").replace("-", " ").replace("_", " ").split() if item}


def event_channels(event: TrustedEvent) -> set[str]:
    tokens = _tokens(event)
    channels: set[str] = set()
    if event.event_type in {"energy_supply", "gold_wti"} or tokens & ENERGY_MARKERS:
        channels.add("energy")
    if tokens & SEMIS_MARKERS:
        channels.add("semis")
    if event.event_type == "sovereign_or_corporate_debt" or tokens & CREDIT_MARKERS:
        channels.add("credit")
    if event.event_type in {"central_bank_rates", "inflation_employment"}:
        channels.add("rates")
    if event.event_type == "company_filing":
        channels.add("company")
    if event.event_type == "war_sanctions" and "energy" in channels:
        channels.add("geo_energy")
    return channels


def why_relevant(event: TrustedEvent, symbol: str) -> dict[str, Any] | None:
    seed = _seed(symbol)
    channels = event_channels(event)
    if not channels:
        return None
    if event.event_type == "vix_risk":
        return None
    if "company" in channels:
        if symbol.upper() in {item.upper() for item in event.entities}:
            return {
                "relevant": True,
                "channel": "company",
                "mechanism": "company_filing",
                "why_relevant": "公司原文公告直接对应本标的",
            }
        return None
    if "energy" in channels or "geo_energy" in channels:
        if "oil_producer" in seed["themes"] or "commodity_revenue" in seed["channels"]:
            return {
                "relevant": True,
                "channel": "commodity_revenue",
                "mechanism": "commodity_price_to_producer_revenue",
                "why_relevant": "原油生产收入直接暴露于供应中断/制裁带来的油价变化，不是把战争标题抄到所有股票",
            }
        if "semis" in channels:
            return None
        if event.event_type == "war_sanctions" and (
            "high_valuation_growth" in seed["themes"] or "semis" in seed["themes"]
        ):
            return {
                "relevant": True,
                "channel": "risk_premium",
                "mechanism": "geopolitical_risk_premium_to_duration",
                "why_relevant": "高估值成长/半导体通过风险溢价和供应链间接暴露，不是油企收入路径",
            }
        if event.event_type == "war_sanctions" and ("banks" in seed["themes"] or "credit" in seed["themes"]):
            return {
                "relevant": True,
                "channel": "risk_premium",
                "mechanism": "risk_premium_to_credit_conditions",
                "why_relevant": "银行通过风险溢价和信用条件暴露，不是油价收入",
            }
        return None
    if "semis" in channels:
        if "semis" in seed["themes"] or "supply_chain" in seed["channels"]:
            return {
                "relevant": True,
                "channel": "supply_chain",
                "mechanism": "export_control_to_semis_supply",
                "why_relevant": "半导体出口限制映射到该股供应链，不复制到原油生产商",
            }
        return None
    if "credit" in channels:
        if "banks" in seed["themes"] or "credit" in seed["themes"]:
            return {
                "relevant": True,
                "channel": "credit_conditions",
                "mechanism": "credit_event_to_bank_balance_sheet",
                "why_relevant": "银行信用/债务事件进入 JPM 观察，不默认进入消费电子或能源股",
            }
        return None
    if "rates" in channels:
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
    return None


def attach_exposures(event: TrustedEvent, symbols: list[str]) -> list[dict[str, Any]]:
    rows = []
    for symbol in symbols:
        hit = why_relevant(event, symbol)
        if not hit:
            continue
        rows.append({"symbol": symbol.upper(), **hit})
    return rows
