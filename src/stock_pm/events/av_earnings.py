"""Alpha Vantage earnings prints. Reuses ALPHA_VANTAGE_API_KEY; keys never stored."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlencode

from stock_pm.config import Settings
from stock_pm.fetch import FetchError, json_get, utc_now

from .bodies import is_allowed_sec_host
from .policy import events_data_mode
from .earnings import (
    AV_EARNINGS_SOURCE,
    AV_ESTIMATES_SOURCE,
    apply_estimate_snapshot,
    associate_sec_filing,
    attach_transcript,
    documents_from_evidence,
    evidence_from_av_quarters,
    fiscal_quarter_id,
    load_frozen_earnings_documents,
    local_degraded_earnings_documents,
    parse_number,
    reset_earnings_registry,
)
from .feeds import RateLimiter, fetch_feed, parse_feed_items
from .types import EventDocument


AV_API = "https://www.alphavantage.co/query"
AV_ENV = "ALPHA_VANTAGE_API_KEY"
SEC_COMPANY_ATOM = "https://www.sec.gov/cgi-bin/browse-edgar"
_RESERVED_UA_HOSTS = frozenset({"example.com", "example.net", "example.org", "localhost"})
_RESERVED_UA_TLDS = frozenset({"test", "invalid", "localhost", "example"})
_LIMITER = RateLimiter(1.1)
_SEC_LIMITER = RateLimiter(0.15)
WATCH_SYMBOLS = ("AAPL", "NVDA", "XOM", "JPM")
WATCH_CIKS = {
    "AAPL": "0000320193",
    "NVDA": "0001045810",
    "XOM": "0000034088",
    "JPM": "0000019617",
}
_SEC_ATOM_CACHE: dict[str, list[dict[str, Any]]] = {}


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
    """Company 8-K search page. Not a citation of a specific earnings print."""
    cik = WATCH_CIKS.get(symbol.upper(), "")
    if not cik:
        return ""
    return f"{SEC_COMPANY_ATOM}?action=getcompany&CIK={cik}&type=8-K&owner=include&count=8"


def company_8k_atom_url(symbol: str) -> str:
    cik = WATCH_CIKS.get(symbol.upper(), "")
    if not cik:
        return ""
    return (
        f"{SEC_COMPANY_ATOM}?action=getcompany&CIK={cik}&type=8-K"
        "&dateb=&owner=include&start=0&count=20&output=atom"
    )


def pick_sec_8k_url(items: list[dict[str, Any]], reported_date: str) -> str:
    """Same calendar day, current 8-K only. Ambiguous or amended filings stay unmatched."""
    day = str(reported_date or "")[:10]
    if len(day) != 10:
        return ""
    hits: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        published = str(item.get("published_at") or "")[:10]
        title = str(item.get("title") or "")
        url = str(item.get("url") or "")
        if published != day:
            continue
        if "8-K/A" in title.upper() or "[Amend]" in title:
            continue
        if not url.startswith("https://www.sec.gov/Archives/edgar/"):
            continue
        if url not in hits:
            hits.append(url)
    if len(hits) != 1:
        return ""
    return hits[0]


def reset_sec_atom_cache() -> None:
    _SEC_ATOM_CACHE.clear()


def configured_sec_user_agent(settings: Settings | None = None) -> str:
    """Real contact UA only. Empty or documented placeholder values do not go to SEC."""
    settings = settings or Settings()
    value = (
        getattr(settings, "sec_edgar_user_agent", None)
        or os.getenv("SEC_EDGAR_USER_AGENT")
        or ""
    ).strip()
    if not _usable_sec_user_agent(value):
        return ""
    return value


def _email_host(value: str) -> str:
    for token in reversed(value.replace("<", " ").replace(">", " ").split()):
        if "@" in token:
            return token.rsplit("@", 1)[-1].strip(".,;>").lower()
    return ""


def _usable_sec_user_agent(value: str) -> bool:
    """Reject empty values and reserved/placeholder mailbox hosts."""
    text = str(value or "").strip()
    if not text or "@" not in text:
        return False
    host = _email_host(text)
    if not host or host in _RESERVED_UA_HOSTS:
        return False
    tld = host.rsplit(".", 1)[-1]
    return tld not in _RESERVED_UA_TLDS


def fetch_company_8k_items(symbol: str, *, settings: Settings | None = None) -> list[dict[str, Any]]:
    user_agent = configured_sec_user_agent(settings)
    if not user_agent:
        return []
    key = symbol.upper()
    if key in _SEC_ATOM_CACHE:
        return list(_SEC_ATOM_CACHE[key])
    url = company_8k_atom_url(key)
    if not url:
        return []
    resp = fetch_feed(
        url,
        user_agent=user_agent,
        extra_headers={"Host": "www.sec.gov"},
        limiter=_SEC_LIMITER,
        timeout=40 if is_allowed_sec_host(url) else 25,
        retries=2,
    )
    if not resp.ok:
        return []
    rows = parse_feed_items(resp.body, base_url=url)
    _SEC_ATOM_CACHE[key] = rows
    return list(rows)


def match_sec_8k_for_print(symbol: str, reported_date: str, *, settings: Settings | None = None) -> str:
    if not configured_sec_user_agent(settings):
        return ""
    return pick_sec_8k_url(fetch_company_8k_items(symbol, settings=settings), reported_date)


def bind_sec_association(row: Any, *, settings: Settings | None = None) -> Any:
    """Associate a same-day 8-K only when a real SEC User-Agent is configured."""
    if not configured_sec_user_agent(settings):
        return associate_sec_filing(row, "", reason_code="sec_user_agent_not_configured")
    return associate_sec_filing(
        row,
        match_sec_8k_for_print(row.symbol, row.published_at or "", settings=settings),
    )


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
            "request_urls": {
                "EARNINGS": av_http_source("EARNINGS", "AAPL"),
                "EARNINGS_ESTIMATES": av_http_source("EARNINGS_ESTIMATES", "AAPL"),
                "EARNINGS_CALL_TRANSCRIPT": av_http_source("EARNINGS_CALL_TRANSCRIPT", "AAPL", quarter="2026Q3"),
            },
            "event_count": 0,
            "required_env": AV_ENV,
        }

    def _fetch_isolated(self, function: str, symbol: str, extra: dict[str, str] | None = None) -> tuple[dict[str, Any] | None, str | None]:
        try:
            return fetch_av_function(function, symbol, settings=self.settings, extra=extra), None
        except FetchError as exc:
            return None, exc.reason_code

    def discover(self) -> list[EventDocument]:
        mode = events_data_mode(self.settings)
        if mode in {"demo", "fixture"}:
            if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("STOCK_PM_EARNINGS_FIXTURE") != "1":
                return []
            reset_earnings_registry()
            rows = load_frozen_earnings_documents()
            rows.extend(local_degraded_earnings_documents())
            return rows
        if mode not in {"empty", "live"}:
            return []
        if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("STOCK_PM_EARNINGS_LIVE") != "1":
            return []
        if not self.configured():
            return []
        rows: list[EventDocument] = []
        fetched_at = utc_now()
        for symbol in WATCH_SYMBOLS:
            payload, _earn_err = self._fetch_isolated("EARNINGS", symbol)
            if not payload:
                continue
            try:
                quarters = parse_av_earnings(payload)
            except FetchError:
                continue
            if not quarters:
                continue
            evidence = evidence_from_av_quarters(
                quarters,
                symbol=symbol,
                fetched_at=fetched_at,
                source_url=AV_EARNINGS_SOURCE.format(symbol=symbol),
            )
            estimates, _est_err = self._fetch_isolated("EARNINGS_ESTIMATES", symbol)
            if estimates:
                try:
                    estimate_rows = parse_av_estimates(estimates)
                except FetchError:
                    estimate_rows = []
                apply_estimate_snapshot(
                    evidence,
                    estimate_rows,
                    fetched_at=fetched_at,
                    source_url=AV_ESTIMATES_SOURCE.format(symbol=symbol),
                )
            elif _est_err and "EARNINGS_ESTIMATES" not in evidence.endpoints_called:
                evidence.endpoints_called.append("EARNINGS_ESTIMATES")
            quarter = evidence.fiscal_quarter or fiscal_quarter_id(symbol, evidence.fiscal_date_ending)
            if quarter:
                transcript, _tr_err = self._fetch_isolated(
                    "EARNINGS_CALL_TRANSCRIPT", symbol, extra={"quarter": quarter}
                )
                if transcript:
                    try:
                        excerpts = parse_av_transcript(
                            transcript, symbol=symbol, quarter=quarter, fetched_at=fetched_at
                        )
                    except FetchError:
                        excerpts = []
                    attach_transcript(
                        evidence,
                        excerpts,
                        quarter=quarter,
                        fetched_at=fetched_at,
                        symbol=symbol,
                    )
                elif _tr_err and "EARNINGS_CALL_TRANSCRIPT" not in evidence.endpoints_called:
                    evidence.endpoints_called.append("EARNINGS_CALL_TRANSCRIPT")
            bind_sec_association(evidence, settings=self.settings)
            rows.extend(documents_from_evidence(evidence))
        return rows


def load_frozen_as_provider() -> list[EventDocument]:
    reset_earnings_registry()
    return load_frozen_earnings_documents()


def parse_av_estimates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("estimates")
    if rows is None:
        rows = payload.get("data")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise FetchError("record_invalid", "Alpha Vantage estimates changed shape")
    return [row for row in rows if isinstance(row, dict)]


def parse_av_transcript(payload: dict[str, Any], *, symbol: str, quarter: str, fetched_at: str) -> list[dict[str, Any]]:
    rows = payload.get("transcript")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise FetchError("record_invalid", "Alpha Vantage transcript changed shape")
    excerpts: list[dict[str, Any]] = []
    for item in rows[:8]:
        if not isinstance(item, dict):
            continue
        excerpts.append(
            {
                "speaker": item.get("speaker"),
                "title": item.get("title"),
                "content": item.get("content"),
                "quarter": payload.get("quarter") or quarter,
                "symbol": symbol,
                "source_url": av_http_source("EARNINGS_CALL_TRANSCRIPT", symbol, quarter=quarter),
                "fetched_at": fetched_at,
            }
        )
    return excerpts
