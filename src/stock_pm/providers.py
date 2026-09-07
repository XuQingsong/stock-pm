from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from .config import Settings


FMP_API = "https://financialmodelingprep.com/stable"


class FundamentalsProvider(Protocol):
    name: str

    def fetch(
        self,
        symbol: str,
        last_price: float | None,
        captured_at: str,
        asset_class: str,
    ) -> dict: ...


def _number(value: Any) -> float | None:
    if value in (None, "", "None", "N/A"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _surprise(actual: float | None, estimate: float | None) -> float | None:
    if actual is None or estimate in (None, 0):
        return None
    return round(100 * (actual - estimate) / abs(estimate), 2)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


class NasdaqProvider:
    """Free fallback: EPS consensus plus news. Revenue/net income stay empty."""

    name = "nasdaq"

    def fetch(
        self,
        symbol: str,
        last_price: float | None,
        captured_at: str,
        asset_class: str,
    ) -> dict:
        from .fundamentals import fetch_symbol

        return fetch_symbol(symbol, last_price, captured_at, asset_class)


class FMPProvider:
    """Paid Financial Modeling Prep adapter for valuation and earnings."""

    name = "fmp"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        query = urlencode({**params, "apikey": self.api_key})
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urlopen(f"{FMP_API}/{path}?{query}", timeout=30) as response:
                    return json.load(response)
            except HTTPError as exc:
                last_error = RuntimeError(f"FMP {path} failed with HTTP {exc.code}")
                if exc.code == 429 and attempt < 2:
                    time.sleep(attempt + 1)
                    continue
                raise last_error from exc
        assert last_error is not None
        raise last_error

    def _try_get(self, path: str, params: dict[str, Any]) -> Any:
        try:
            return self._get(path, params)
        except RuntimeError as exc:
            if "HTTP 402" in str(exc) or "HTTP 429" in str(exc):
                return []
            raise

    def fetch(
        self,
        symbol: str,
        last_price: float | None,
        captured_at: str,
        asset_class: str,
    ) -> dict:
        from .fundamentals import _news

        profile = _first_row(self._try_get("profile", {"symbol": symbol}))
        ratios = _first_row(self._try_get("ratios-ttm", {"symbol": symbol}))
        metrics = _first_row(self._try_get("key-metrics-ttm", {"symbol": symbol}))
        income = self._try_get("income-statement", {"symbol": symbol, "period": "quarter"}) or []
        reported = self._try_get("earnings", {"symbol": symbol}) or []
        if not isinstance(income, list):
            income = []
        if not isinstance(reported, list):
            reported = []
        income = income[:8]

        pe_ttm = _number(ratios.get("priceToEarningsRatioTTM"))
        if pe_ttm is None and last_price and _number(metrics.get("netIncomePerShareTTM")):
            eps = _number(metrics.get("netIncomePerShareTTM"))
            pe_ttm = last_price / eps if eps else None
        revenue_yoy, eps_yoy, revenue_ttm = _growth_from_income(income)

        fundamental = {
            "symbol": symbol,
            "captured_at": captured_at,
            "currency": profile.get("currency") or "USD",
            "market_cap": _number(profile.get("marketCap")),
            "enterprise_value": _number(metrics.get("enterpriseValueTTM")),
            "pe_ttm": pe_ttm,
            "pe_forward": None,
            "peg_ratio": _number(ratios.get("priceToEarningsGrowthRatioTTM")),
            "price_to_book": _number(ratios.get("priceToBookRatioTTM")),
            "price_to_sales": _number(ratios.get("priceToSalesRatioTTM")),
            "ev_to_ebitda": _number(metrics.get("evToEBITDATTM")),
            "eps_ttm": _number(metrics.get("netIncomePerShareTTM")),
            "revenue_ttm": revenue_ttm,
            "gross_margin_pct": _pct(ratios.get("grossProfitMarginTTM")),
            "operating_margin_pct": _pct(ratios.get("operatingProfitMarginTTM")),
            "net_margin_pct": _pct(ratios.get("netProfitMarginTTM")),
            "revenue_growth_yoy_pct": revenue_yoy,
            "eps_growth_yoy_pct": eps_yoy,
            "dividend_yield_pct": _pct(ratios.get("dividendYieldTTM") or ratios.get("dividendYielTTM")),
            "beta": _number(profile.get("beta")),
            "analyst_target_price": None,
            "source": "FMP profile + ratios-ttm + key-metrics-ttm",
            "raw": {"profile": profile, "ratios": ratios, "metrics": metrics},
        }

        earnings = _merge_fmp_earnings(symbol, reported, income)
        return {
            "fundamental": fundamental,
            "earnings": earnings,
            "news": _news(symbol),
        }


def _first_row(payload: Any) -> dict:
    if isinstance(payload, list):
        return payload[0] if payload and isinstance(payload[0], dict) else {}
    if isinstance(payload, dict):
        return payload
    return {}


def _fiscal_year_value(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        year = int(float(value))
    except (TypeError, ValueError):
        return None
    return year if 1900 <= year <= 2100 else None


def _pct(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    return round(100 * number, 2) if abs(number) <= 1.5 else round(number, 2)


def _growth_from_income(income: list[dict]) -> tuple[float | None, float | None, float | None]:
    latest = income[0] if income else {}
    year_ago = income[4] if len(income) > 4 else {}
    revenue_now = _number(latest.get("revenue"))
    revenue_old = _number(year_ago.get("revenue"))
    eps_now = _number(latest.get("eps") or latest.get("epsdiluted"))
    eps_old = _number(year_ago.get("eps") or year_ago.get("epsdiluted"))
    revenue_yoy = (
        round(100 * (revenue_now / revenue_old - 1), 2)
        if revenue_now and revenue_old
        else None
    )
    eps_yoy = round(100 * (eps_now / eps_old - 1), 2) if eps_now and eps_old else None
    trailing = [_number(row.get("revenue")) for row in income[:4]]
    revenue_ttm = sum(trailing) if trailing and all(item is not None for item in trailing) else None
    return revenue_yoy, eps_yoy, revenue_ttm


def _merge_fmp_earnings(symbol: str, reported: list[dict], income: list[dict]) -> list[dict]:
    """Join FMP earnings surprises with quarterly income-statement net income."""
    income_rows = sorted(
        [row for row in income if _parse_date(row.get("date"))],
        key=lambda row: row["date"],
        reverse=True,
    )
    result = []
    used_income: set[str] = set()
    for row in reported:
        report_date = _parse_date(row.get("date"))
        if report_date is None:
            continue
        eps_actual = _number(row.get("epsActual"))
        revenue_actual = _number(row.get("revenueActual"))
        if eps_actual is None and revenue_actual is None:
            continue
        matched = None
        for item in income_rows:
            period_end = _parse_date(item.get("date"))
            key = item["date"]
            if key in used_income or period_end is None:
                continue
            if period_end <= report_date <= period_end + timedelta(days=95):
                matched = item
                used_income.add(key)
                break
        eps_estimate = _number(row.get("epsEstimated"))
        revenue_estimate = _number(row.get("revenueEstimated"))
        net_income_actual = _number((matched or {}).get("netIncome"))
        result.append(
            {
                "symbol": symbol,
                "report_date": report_date.isoformat(),
                "report_timing": "unknown",
                "fiscal_period": (matched or {}).get("period") or "Quarter",
                "fiscal_year": _fiscal_year_value((matched or {}).get("fiscalYear")),
                "period_end": (matched or {}).get("date"),
                "currency": (matched or {}).get("reportedCurrency") or "USD",
                "eps_actual": eps_actual,
                "eps_estimate": eps_estimate,
                "eps_surprise_pct": _surprise(eps_actual, eps_estimate),
                "revenue_actual": revenue_actual,
                "revenue_estimate": revenue_estimate,
                "revenue_surprise_pct": _surprise(revenue_actual, revenue_estimate),
                "net_income_actual": net_income_actual,
                "net_income_estimate": None,
                "net_income_surprise_pct": None,
                "provider_fields": {
                    "eps": "fmp.earnings",
                    "revenue": "fmp.earnings",
                    "net_income_actual": "fmp.income-statement" if net_income_actual is not None else None,
                    "net_income_estimate": None,
                },
                "source": "FMP earnings + income-statement",
                "raw": {"earnings": row, "income": matched},
            }
        )
    result.sort(key=lambda row: row["report_date"], reverse=True)
    return result[:12]


def get_fundamentals_provider(name: str | None = None) -> FundamentalsProvider:
    settings = Settings()
    selected = name or ("fmp" if settings.fmp_api_key else "nasdaq")
    if selected == "fmp":
        if not settings.fmp_api_key:
            raise ValueError("FMP_API_KEY is not configured")
        return FMPProvider(settings.fmp_api_key)
    if selected == "nasdaq":
        return NasdaqProvider()
    raise ValueError(f"Unknown fundamentals provider: {selected}")
