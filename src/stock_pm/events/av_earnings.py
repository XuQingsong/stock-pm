"""Alpha Vantage earnings prints. Reuses ALPHA_VANTAGE_API_KEY; keys never stored."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlencode

from stock_pm.config import Settings
from stock_pm.fetch import FetchError, json_get, utc_now

from .policy import events_data_mode
from .earnings import (
    AV_EARNINGS_SOURCE,
    attach_transcript,
    documents_from_evidence,
    evidence_from_av_quarters,
    parse_number,
    reset_earnings_registry,
)
from .feeds import RateLimiter
from .types import EventDocument


AV_API = "https://www.alphavantage.co/query"
AV_ENV = "ALPHA_VANTAGE_API_KEY"
_LIMITER = RateLimiter(1.1)
WATCH_SYMBOLS = ("AAPL", "NVDA", "XOM", "JPM")
WATCH_CIKS = {
    "AAPL": "0000320193",
    "NVDA": "0001045810",
    "XOM": "0000034088",
    "JPM": "0000019617",
}


def av_http_source(function: str, symbol: str, **extra: str) -> str:
    query = urlencode({"function": function, "symbol": symbol.upper(), **extra})
    return f"{AV_API}?{query}"


def _key(settings: Settings | None = None) -> str:
    settings = settings or Settings()
    return (
        getattr(settings, "alpha_vantage_api_key", None)
        or os.getenv(AV_ENV)
        or ""
    ).strip()


def fetch_av_function(function: str, symbol: str, *, settings: Settings | None = None, extra: dict[str, str] | None = None) -> dict[str, Any]:
    key = _key(settings)
    if not key:
        raise FetchError("source_not_configured", f"{AV_ENV} is required")
    params = {"function": function, "symbol": symbol.upper(), "apikey": key}
    if extra:
        params.update(extra)
    _LIMITER.wait()
    result = json_get(
        f"{AV_API}?{urlencode(params)}",
        timeout=25,
        retries=2,
        cache_key=f"av-{function}-{symbol.upper()}-{'-'.join(sorted((extra or {}).values()))}",
    )
    payload = result.payload
    if not isinstance(payload, dict):
        raise FetchError("record_invalid", "Alpha Vantage earnings payload is not an object")
    if payload.get("Note") or payload.get("Information"):
        if result.from_cache:
            return payload
        raise FetchError("rate_limited", "Alpha Vantage earnings rate limited")
    if payload.get("Error Message"):
        raise FetchError("query_error", "Alpha Vantage earnings query failed")
    return payload


def parse_av_earnings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("quarterlyEarnings")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise FetchError("record_invalid", "Alpha Vantage earnings changed shape")
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if parse_number(row.get("reportedEPS")) is None:
            continue
        out.append(row)
    return out


def sec_company_8k_url(symbol: str) -> str:
    cik = WATCH_CIKS.get(symbol.upper(), "")
    if not cik:
        return ""
    return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=8-K&owner=include&count=8"


class AvEarningsProvider:
    name = "alpha_vantage_earnings"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    def configured(self) -> bool:
        return bool(_key(self.settings))

    def status(self) -> dict[str, Any]:
        if not self.configured():
            return {
                "provider": self.name,
                "status": "not_configured",
                "live": False,
                "reason_code": "source_not_configured",
                "role": "structured_earnings",
                "request_url": av_http_source("EARNINGS", "AAPL"),
                "event_count": 0,
                "required_env": AV_ENV,
            }
        return {
            "provider": self.name,
            "status": "ok",
            "live": True,
            "reason_code": None,
            "role": "structured_earnings",
            "request_url": av_http_source("EARNINGS", "AAPL"),
            "event_count": 0,
            "required_env": AV_ENV,
        }

    def discover(self) -> list[EventDocument]:
        if events_data_mode(self.settings) not in {"empty", "live"}:
            return []
        if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("STOCK_PM_EARNINGS_LIVE") != "1":
            return []
        if not self.configured():
            return []
        rows: list[EventDocument] = []
        fetched_at = utc_now()
        for symbol in WATCH_SYMBOLS:
            try:
                payload = fetch_av_function("EARNINGS", symbol, settings=self.settings)
                quarters = parse_av_earnings(payload)
                if not quarters:
                    continue
                evidence = evidence_from_av_quarters(
                    quarters,
                    symbol=symbol,
                    fetched_at=fetched_at,
                    source_url=AV_EARNINGS_SOURCE.format(symbol=symbol),
                )
                rows.extend(documents_from_evidence(evidence, sec_url=sec_company_8k_url(symbol)))
            except FetchError:
                continue
        return rows


def load_frozen_as_provider() -> list[EventDocument]:
    from .earnings import load_frozen_earnings_documents

    reset_earnings_registry()
    return load_frozen_earnings_documents()


def optional_transcript(symbol: str, quarter: str, evidence) -> None:
    try:
        payload = fetch_av_function(
            "EARNINGS_CALL_TRANSCRIPT",
            symbol,
            extra={"quarter": quarter},
        )
    except FetchError:
        return
    excerpts = []
    for item in list(payload.get("transcript") or [])[:8]:
        if not isinstance(item, dict):
            continue
        excerpts.append(
            {
                "speaker": item.get("speaker"),
                "title": item.get("title"),
                "content": item.get("content"),
                "quarter": payload.get("quarter") or quarter,
                "source_url": av_http_source("EARNINGS_CALL_TRANSCRIPT", symbol, quarter=quarter),
            }
        )
    attach_transcript(evidence, excerpts, quarter=quarter)
