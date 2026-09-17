"""Deterministic company header from Research Pack. LLM never owns these numbers."""

from __future__ import annotations

from typing import Any

from stock_pm.research.extract import pct_change, to_number, yoy_from_quarters


def _metric(value: Any, origin: str, *, field: str) -> dict[str, Any]:
    number = to_number(value)
    if number is None:
        return {"field": field, "value": None, "origin": "unavailable", "display": "unavailable"}
    return {"field": field, "value": number, "origin": origin, "display": number}


def _latest_print(pack: dict[str, Any]) -> dict[str, Any]:
    rows = [row for row in (pack.get("earnings_history") or []) if isinstance(row, dict)]
    return rows[0] if rows else {}


def company_header(pack: dict[str, Any] | None, *, issuer: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = pack or {}
    profile = dict(payload.get("company_profile") or {})
    issuer = issuer or {}
    latest = _latest_print(payload)
    closes = list(profile.get("recent_closes") or [])
    last_close = to_number(profile.get("last_close"))
    price_ts = None
    if closes:
        last = closes[-1] if isinstance(closes[-1], dict) else {}
        price_ts = last.get("session_date") or last.get("date")
        if last_close is None:
            last_close = to_number(last.get("close") or last.get("close_price"))
    earnings = list(payload.get("earnings_history") or [])
    guidance = list(payload.get("guidance_history") or [])
    missing = [str(item) for item in (payload.get("missing_fields") or [])]
    rev_growth = to_number(profile.get("revenue_growth_yoy_pct")) or yoy_from_quarters(earnings, "revenue")
    eps_growth = to_number(profile.get("eps_growth_yoy_pct")) or yoy_from_quarters(earnings, "eps")
    q_rev_yoy = pct_change(to_number(latest.get("revenue")), to_number(earnings[4].get("revenue")) if len(earnings) > 4 else None)
    q_eps_yoy = pct_change(to_number(latest.get("eps")), to_number(earnings[4].get("eps")) if len(earnings) > 4 else None)
    fcf = to_number(profile.get("fcf") or latest.get("fcf"))
    market_cap = to_number(profile.get("market_cap"))
    fcf_yield = None
    if fcf not in (None, 0) and market_cap not in (None, 0):
        fcf_yield = round(100.0 * float(fcf) / float(market_cap), 2)
    latest_guidance = guidance[0] if guidance else {}
    return {
        "ticker": payload.get("ticker") or issuer.get("ticker"),
        "company_name": profile.get("legal_name") or issuer.get("legal_name"),
        "sector": profile.get("sector") or issuer.get("sector"),
        "industry": profile.get("industry") or profile.get("gics") or issuer.get("gics"),
        "template_id": payload.get("template_id"),
        "price": _metric(last_close, "reported", field="price"),
        "price_timestamp": price_ts or payload.get("updated_at"),
        "market_cap": _metric(market_cap, "reported", field="market_cap"),
        "valuation": {
            "pe_ttm": _metric(profile.get("pe_ttm"), "reported", field="pe_ttm"),
            "pe_forward": _metric(profile.get("pe_forward"), "consensus" if profile.get("pe_forward") else "unavailable", field="pe_forward"),
            "ps": _metric(profile.get("ps_ttm") or profile.get("price_to_sales"), "reported", field="ps"),
            "ev_ebitda": _metric(profile.get("ev_ebitda"), "reported", field="ev_ebitda"),
            "fcf_yield": _metric(fcf_yield, "reported" if fcf_yield is not None else "unavailable", field="fcf_yield"),
        },
        "growth": {
            "revenue_ttm": _metric(profile.get("revenue_ttm"), "reported", field="revenue_ttm"),
            "revenue_growth_yoy": _metric(rev_growth, "reported", field="revenue_growth_yoy"),
            "eps_ttm": _metric(profile.get("eps_ttm"), "reported", field="eps_ttm"),
            "eps_growth_yoy": _metric(eps_growth, "reported", field="eps_growth_yoy"),
        },
        "latest_quarter": {
            "report_date": latest.get("report_date") or latest.get("period_end"),
            "fiscal_period": latest.get("fiscal_period"),
            "revenue": _metric(latest.get("revenue"), "reported", field="quarter_revenue"),
            "revenue_yoy": _metric(q_rev_yoy, "reported", field="quarter_revenue_yoy"),
            "eps": _metric(latest.get("eps"), "reported", field="quarter_eps"),
            "eps_yoy": _metric(q_eps_yoy, "reported", field="quarter_eps_yoy"),
            "gross_margin": _metric(latest.get("gross_margin_pct") or profile.get("gross_margin_pct"), "reported", field="gross_margin"),
            "operating_margin": _metric(latest.get("operating_margin_pct") or profile.get("operating_margin_pct"), "reported", field="operating_margin"),
            "fcf": _metric(latest.get("fcf") or profile.get("fcf"), "reported", field="quarter_fcf"),
            "source": latest.get("source") or "earnings_history",
        },
        "forward": {
            "management_guidance": {
                "origin": "reported" if latest_guidance else "unavailable",
                "text": (latest_guidance.get("text") or latest_guidance.get("excerpt") or latest_guidance.get("quote") or None),
                "source": latest_guidance.get("source"),
                "count": len(guidance),
            },
            "consensus": {
                "origin": "unavailable",
                "reason": "no trusted consensus source is wired for Brain Phase 1",
            },
            "system_forecast": {
                "origin": "unavailable",
                "reason": "Phase 1 does not run a system forecast",
            },
        },
        "missing_fields": missing,
        "pack_updated_at": payload.get("updated_at"),
        "is_fixture": bool(payload.get("is_fixture")),
        "source": payload.get("source") or "production",
    }
