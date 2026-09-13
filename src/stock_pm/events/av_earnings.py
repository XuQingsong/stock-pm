"""Alpha Vantage earnings prints. Reuses ALPHA_VANTAGE_API_KEY; keys never stored."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlencode

from stock_pm.config import Settings
from stock_pm.fetch import FetchError, json_get, read_cache, utc_now

from .bodies import is_allowed_sec_host
from .earnings import (
    AV_EARNINGS_SOURCE,
    AV_ESTIMATES_SOURCE,
    apply_estimate_snapshot,
    associate_sec_filing,
    attach_transcript,
    documents_from_evidence,
    evidence_from_av_quarters,
    fiscal_quarter_id,
    load_frozen_coverage_documents,
    load_frozen_earnings_documents,
    local_degraded_earnings_documents,
    parse_number,
    reset_earnings_registry,
)
from .earnings_health import (
    current_earnings_health,
    empty_fields,
    fields_from_evidence,
    injected_reason,
    next_retry_at,
    parse_inject_env,
    persist_health,
    reset_earnings_health,
    reset_earnings_inject,
    summarize_health,
    symbol_health,
)
from .feeds import RateLimiter, fetch_feed, parse_feed_items
from .policy import events_data_mode
from .types import EventDocument
from .watchlist import resolve_watchlist


AV_API = "https://www.alphavantage.co/query"
AV_ENV = "ALPHA_VANTAGE_API_KEY"
SEC_COMPANY_ATOM = "https://www.sec.gov/cgi-bin/browse-edgar"
_RESERVED_UA_HOSTS = frozenset({"example.com", "example.net", "example.org", "localhost"})
_RESERVED_UA_TLDS = frozenset({"test", "invalid", "localhost", "example"})
_LIMITER = RateLimiter(1.1)
_SEC_LIMITER = RateLimiter(0.15)
# Inverted EDGAR CIKs for seeded stocks. Unknown issuers stay unmatched; do not invent CIKs.
WATCH_CIKS = {
    "AAPL": "0000320193",
    "NVDA": "0001045810",
    "XOM": "0000034088",
    "JPM": "0000019617",
    "MU": "0000723125",
    "INTC": "0000050863",
    "GOOGL": "0001652044",
    "AVGO": "0001730168",
    "NOK": "0000924619",
}
_SEC_ATOM_CACHE: dict[str, list[dict[str, Any]]] = {}
AV_FUNCTIONS = ("EARNINGS", "EARNINGS_ESTIMATES", "EARNINGS_CALL_TRANSCRIPT")


def av_http_source(function: str, symbol: str, **extra: str) -> str:
    query = urlencode({"function": function, "symbol": symbol.upper(), **extra})
    return f"{AV_API}?{query}"


def av_cache_key(function: str, symbol: str, extra: dict[str, str] | None = None) -> str:
    return f"av-{function}-{symbol.upper()}-{'-'.join(sorted((extra or {}).values()))}"


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
        cache_key=av_cache_key(function, symbol, extra),
    )
    payload = result.payload
    if not isinstance(payload, dict):
        raise FetchError("record_invalid", "Alpha Vantage earnings payload is not an object")
    if payload.get("Note") or payload.get("Information"):
        if result.from_cache:
            return payload
        raise FetchError("rate_limited", "Alpha Vantage earnings rate limited")
    if payload.get("Error Message"):
        raise FetchError("unsupported", "Alpha Vantage earnings query is not supported for this symbol")
    return payload


def read_av_cache(function: str, symbol: str, extra: dict[str, str] | None = None) -> dict[str, Any] | None:
    cached = read_cache(av_cache_key(function, symbol, extra))
    if not cached or not isinstance(cached.get("payload"), dict):
        return None
    payload = cached["payload"]
    if payload.get("Note") or payload.get("Information") or payload.get("Error Message"):
        return None
    return cached


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


def _budget(settings: Settings | None) -> int:
    settings = settings or Settings()
    try:
        return max(1, int(getattr(settings, "earnings_av_budget", None) or os.getenv("STOCK_PM_EARNINGS_BUDGET") or 8))
    except (TypeError, ValueError):
        return 8


def _prioritize_symbols(stocks: list[str], previous: dict[str, Any]) -> list[str]:
    rows = (previous.get("symbols") or {}) if previous else {}

    def score(symbol: str) -> tuple[int, str]:
        row = rows.get(symbol) or {}
        stamp = str(row.get("last_success_at") or "")
        missing = list(row.get("missing_fields") or [])
        if not row:
            return (0, "")
        if missing or row.get("reason_code") in {"rate_limited", "upstream_empty", "query_error"}:
            return (1, stamp)
        return (2, stamp)

    return sorted(stocks, key=score)


def apply_frozen_health(pack: dict[str, Any], *, stocks: list[str], etfs: list[str]) -> dict[str, Any]:
    fetched_at = str(pack.get("fetched_at") or utc_now())
    declared = pack.get("health") or {}
    from .earnings import earnings_for

    symbols: dict[str, Any] = {}
    for symbol in stocks:
        row = declared.get(symbol) or {}
        evidence = earnings_for(symbol)
        source = str(row.get("source") or "frozen")
        if evidence is None:
            symbols[symbol] = symbol_health(
                symbol,
                asset_class="stocks",
                supported=row.get("supported", True),
                fields=empty_fields(reason_code=str(row.get("reason_code") or "upstream_empty"), source="frozen", fetched_at=fetched_at),
                reason_code=str(row.get("reason_code") or "upstream_empty"),
                source="frozen",
                scenario=row.get("scenario") or "missing",
            )
            continue
        outcomes = {}
        if row.get("reason_code") == "rate_limited" or source == "cache":
            outcomes["EARNINGS"] = {
                "reason_code": "rate_limited" if row.get("reason_code") == "rate_limited" else "stale",
                "source": "cache",
                "fetched_at": fetched_at,
                "last_success_at": fetched_at,
            }
        fields = fields_from_evidence(evidence, outcomes=outcomes, source=source)
        missing = [name for name in ("actual", "prior", "consensus") if getattr(evidence, {"prior": "prior_year_actual"}.get(name, name), None) is None]
        if row.get("missing"):
            missing = list(row["missing"])
        symbols[symbol] = symbol_health(
            symbol,
            asset_class="stocks",
            supported=True,
            fields=fields,
            reason_code=row.get("reason_code") or evidence.gap,
            last_success_at=fetched_at,
            implication=evidence.implication,
            scenario=row.get("scenario") or ("complete" if evidence.complete() else "partial"),
            source=source,
            gap=evidence.gap,
            missing_fields=missing if evidence.gap else [],
        )
    for symbol in etfs:
        row = declared.get(symbol) or {}
        symbols[symbol] = symbol_health(
            symbol,
            asset_class="etf",
            supported=False,
            fields=empty_fields(reason_code="unsupported", source="none", fetched_at=fetched_at),
            reason_code="unsupported",
            scenario=row.get("scenario") or "unsupported",
            source="none",
        )
    report = {
        "live": False,
        "data_class": "frozen_provider_audit",
        "as_of": fetched_at,
        "fetched_at": fetched_at,
        "budget": {"max_calls": 0, "used": 0, "source": "frozen"},
        "symbols": symbols,
        "note": "Frozen/fixture coverage is not production live coverage.",
    }
    persist_health(report)
    return report


class AvEarningsProvider:
    name = "alpha_vantage_earnings"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self._last_report: dict[str, Any] = {}

    def configured(self) -> bool:
        return bool(_key(self.settings))

    def status(self) -> dict[str, Any]:
        health = summarize_health(self._last_report or current_earnings_health())
        last_success = health.get("as_of")
        symbols = health.get("symbols") or {}
        stamps = [str(row.get("last_success_at") or "") for row in symbols.values() if isinstance(row, dict) and row.get("last_success_at")]
        if stamps:
            last_success = max(stamps)
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
                "last_success_at": last_success,
                "earnings_coverage": health,
            }
        mode = events_data_mode(self.settings)
        live = mode not in {"demo", "fixture", "recorded_replay"} and bool(health.get("live"))
        return {
            "provider": self.name,
            "status": "ok" if (health.get("complete_count") or health.get("partial_count")) else "idle",
            "live": live,
            "reason_code": None if live or mode in {"demo", "fixture"} else "live_coverage_incomplete",
            "role": "structured_earnings",
            "request_url": av_http_source("EARNINGS", "AAPL"),
            "request_urls": {
                "EARNINGS": av_http_source("EARNINGS", "AAPL"),
                "EARNINGS_ESTIMATES": av_http_source("EARNINGS_ESTIMATES", "AAPL"),
                "EARNINGS_CALL_TRANSCRIPT": av_http_source("EARNINGS_CALL_TRANSCRIPT", "AAPL", quarter="2026Q3"),
            },
            "event_count": int(health.get("complete_count") or 0) + int(health.get("partial_count") or 0),
            "required_env": AV_ENV,
            "last_success_at": last_success,
            "earnings_coverage": health,
        }

    def _fetch_isolated(
        self, function: str, symbol: str, extra: dict[str, str] | None = None
    ) -> tuple[dict[str, Any] | None, str | None, str]:
        inject = injected_reason(symbol, function)
        if inject:
            cached = read_av_cache(function, symbol, extra)
            if inject == "rate_limited" and cached:
                return cached["payload"], "rate_limited", "cache"
            return None, inject, "none"
        try:
            payload = fetch_av_function(function, symbol, settings=self.settings, extra=extra)
            return payload, None, "live"
        except FetchError as exc:
            cached = read_av_cache(function, symbol, extra)
            if cached:
                reason = "rate_limited" if exc.reason_code == "rate_limited" else "stale"
                return cached["payload"], reason, "cache"
            return None, exc.reason_code, "none"
        except Exception:
            cached = read_av_cache(function, symbol, extra)
            if cached:
                return cached["payload"], "stale", "cache"
            return None, "query_error", "none"

    def _evidence_from_payload(
        self,
        symbol: str,
        payload: dict[str, Any],
        *,
        fetched_at: str,
        estimates: dict[str, Any] | None,
        transcript: dict[str, Any] | None,
        quarter: str,
    ) -> Any | None:
        try:
            quarters = parse_av_earnings(payload)
        except FetchError:
            return None
        if not quarters:
            return None
        evidence = evidence_from_av_quarters(
            quarters,
            symbol=symbol,
            fetched_at=fetched_at,
            source_url=AV_EARNINGS_SOURCE.format(symbol=symbol),
        )
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
        elif "EARNINGS_ESTIMATES" not in evidence.endpoints_called:
            evidence.endpoints_called.append("EARNINGS_ESTIMATES")
        want_quarter = evidence.fiscal_quarter or quarter
        if transcript and want_quarter:
            try:
                excerpts = parse_av_transcript(
                    transcript, symbol=symbol, quarter=want_quarter, fetched_at=fetched_at
                )
            except FetchError:
                excerpts = []
            attach_transcript(evidence, excerpts, quarter=want_quarter, fetched_at=fetched_at, symbol=symbol)
        bind_sec_association(evidence, settings=self.settings)
        return evidence

    def _symbol_from_cache(self, symbol: str, fetched_at: str) -> tuple[Any | None, dict[str, dict[str, Any]]]:
        outcomes: dict[str, dict[str, Any]] = {}
        cached = read_av_cache("EARNINGS", symbol)
        if not cached:
            return None, outcomes
        outcomes["EARNINGS"] = {
            "reason_code": "stale",
            "source": "cache",
            "fetched_at": str(cached.get("fetched_at") or fetched_at),
            "last_success_at": str(cached.get("fetched_at") or fetched_at),
        }
        estimates_cached = read_av_cache("EARNINGS_ESTIMATES", symbol)
        estimates = estimates_cached["payload"] if estimates_cached else None
        if estimates_cached:
            outcomes["EARNINGS_ESTIMATES"] = {
                "reason_code": "stale",
                "source": "cache",
                "fetched_at": str(estimates_cached.get("fetched_at") or fetched_at),
                "last_success_at": str(estimates_cached.get("fetched_at") or fetched_at),
            }
        evidence = self._evidence_from_payload(
            symbol,
            cached["payload"],
            fetched_at=str(cached.get("fetched_at") or fetched_at),
            estimates=estimates,
            transcript=None,
            quarter="",
        )
        if evidence is None:
            return None, outcomes
        quarter = evidence.fiscal_quarter or fiscal_quarter_id(symbol, evidence.fiscal_date_ending)
        if quarter:
            tr_cached = read_av_cache("EARNINGS_CALL_TRANSCRIPT", symbol, {"quarter": quarter})
            if tr_cached:
                outcomes["EARNINGS_CALL_TRANSCRIPT"] = {
                    "reason_code": "stale",
                    "source": "cache",
                    "fetched_at": str(tr_cached.get("fetched_at") or fetched_at),
                    "last_success_at": str(tr_cached.get("fetched_at") or fetched_at),
                }
                evidence = self._evidence_from_payload(
                    symbol,
                    cached["payload"],
                    fetched_at=str(cached.get("fetched_at") or fetched_at),
                    estimates=estimates,
                    transcript=tr_cached["payload"],
                    quarter=quarter,
                )
        return evidence, outcomes

    def _discover_live(self) -> list[EventDocument]:
        parse_inject_env()
        universe = resolve_watchlist(self.settings)
        stocks = universe["stocks"]
        etfs = universe["etfs"]
        fetched_at = utc_now()
        previous = current_earnings_health()
        budget = _budget(self.settings)
        used = 0
        rows: list[EventDocument] = []
        symbols: dict[str, Any] = {}

        if not self.configured():
            for symbol in stocks:
                symbols[symbol] = symbol_health(
                    symbol,
                    asset_class="stocks",
                    supported=True,
                    fields=empty_fields(reason_code="not_configured", fetched_at=fetched_at),
                    reason_code="not_configured",
                    source="none",
                    scenario="not_configured",
                )
            for symbol in etfs:
                symbols[symbol] = symbol_health(
                    symbol,
                    asset_class="etf",
                    supported=False,
                    fields=empty_fields(reason_code="unsupported", fetched_at=fetched_at),
                    reason_code="unsupported",
                    source="none",
                    scenario="unsupported",
                )
            report = {
                "live": False,
                "data_class": "live_current",
                "as_of": fetched_at,
                "budget": {"max_calls": budget, "used": 0},
                "symbols": symbols,
                "note": "ALPHA_VANTAGE_API_KEY is not configured. No fixture was loaded.",
            }
            persist_health(report)
            self._last_report = report
            return []

        for symbol in etfs:
            symbols[symbol] = symbol_health(
                symbol,
                asset_class="etf",
                supported=False,
                fields=empty_fields(reason_code="unsupported", fetched_at=fetched_at),
                reason_code="unsupported",
                source="none",
                scenario="unsupported",
            )

        for symbol in _prioritize_symbols(stocks, previous):
            outcomes: dict[str, dict[str, Any]] = {}
            payload = None
            estimates = None
            transcript = None
            live_source = "none"
            try:
                if injected_reason(symbol) == "unsupported":
                    symbols[symbol] = symbol_health(
                        symbol,
                        asset_class="stocks",
                        supported=False,
                        fields=empty_fields(reason_code="unsupported", fetched_at=fetched_at),
                        reason_code="unsupported",
                        source="none",
                        scenario="unsupported",
                    )
                    continue
                if used < budget:
                    payload, earn_err, earn_src = self._fetch_isolated("EARNINGS", symbol)
                    used += 1
                    outcomes["EARNINGS"] = {
                        "reason_code": earn_err,
                        "source": earn_src,
                        "fetched_at": fetched_at,
                        "last_success_at": fetched_at if payload else None,
                    }
                    live_source = earn_src
                    quarter = ""
                    if payload:
                        try:
                            quarters = parse_av_earnings(payload)
                        except FetchError:
                            quarters = []
                        if quarters:
                            preview = evidence_from_av_quarters(
                                quarters,
                                symbol=symbol,
                                fetched_at=fetched_at,
                                source_url=AV_EARNINGS_SOURCE.format(symbol=symbol),
                            )
                            quarter = preview.fiscal_quarter or fiscal_quarter_id(symbol, preview.fiscal_date_ending)
                    if used < budget:
                        estimates, est_err, est_src = self._fetch_isolated("EARNINGS_ESTIMATES", symbol)
                        used += 1
                        outcomes["EARNINGS_ESTIMATES"] = {
                            "reason_code": est_err,
                            "source": est_src,
                            "fetched_at": fetched_at,
                            "last_success_at": fetched_at if estimates else None,
                        }
                    if quarter and used < budget:
                        transcript, tr_err, tr_src = self._fetch_isolated(
                            "EARNINGS_CALL_TRANSCRIPT", symbol, extra={"quarter": quarter}
                        )
                        used += 1
                        outcomes["EARNINGS_CALL_TRANSCRIPT"] = {
                            "reason_code": tr_err,
                            "source": tr_src,
                            "fetched_at": fetched_at,
                            "last_success_at": fetched_at if transcript else None,
                        }
                    evidence = None
                    if payload:
                        evidence = self._evidence_from_payload(
                            symbol,
                            payload,
                            fetched_at=fetched_at,
                            estimates=estimates,
                            transcript=transcript,
                            quarter=quarter,
                        )
                    if evidence is None:
                        cached_evidence, cached_outcomes = self._symbol_from_cache(symbol, fetched_at)
                        evidence = cached_evidence
                        if cached_outcomes:
                            outcomes.update({key: value for key, value in cached_outcomes.items() if key not in outcomes or not outcomes[key].get("last_success_at")})
                            live_source = "cache"
                    if evidence is None:
                        reason = (outcomes.get("EARNINGS") or {}).get("reason_code") or "upstream_empty"
                        symbols[symbol] = symbol_health(
                            symbol,
                            asset_class="stocks",
                            supported=reason != "unsupported",
                            fields=empty_fields(reason_code=reason, source=live_source, fetched_at=fetched_at),
                            reason_code=reason,
                            source=live_source,
                            scenario="partial" if reason != "unsupported" else "unsupported",
                            next_retry=next_retry_at(reason, now=fetched_at),
                        )
                        continue
                    rows.extend(documents_from_evidence(evidence))
                    missing = [
                        name
                        for name, attr in (("actual", "actual"), ("prior", "prior_year_actual"), ("consensus", "consensus"))
                        if getattr(evidence, attr, None) is None
                    ]
                    if not evidence.transcript_excerpts:
                        missing.append("transcript")
                    symbols[symbol] = symbol_health(
                        symbol,
                        asset_class="stocks",
                        supported=True,
                        fields=fields_from_evidence(evidence, outcomes=outcomes, source=live_source),
                        reason_code=evidence.gap or (outcomes.get("EARNINGS") or {}).get("reason_code"),
                        last_success_at=evidence.fetched_at,
                        implication=evidence.implication,
                        scenario="complete" if evidence.complete() else "partial",
                        source=live_source,
                        gap=evidence.gap,
                        missing_fields=missing if evidence.gap or "transcript" in missing else [],
                    )
                    continue
                cached_evidence, cached_outcomes = self._symbol_from_cache(symbol, fetched_at)
                if cached_evidence is not None:
                    rows.extend(documents_from_evidence(cached_evidence))
                    missing = [
                        name
                        for name, attr in (("actual", "actual"), ("prior", "prior_year_actual"), ("consensus", "consensus"))
                        if getattr(cached_evidence, attr, None) is None
                    ]
                    symbols[symbol] = symbol_health(
                        symbol,
                        asset_class="stocks",
                        supported=True,
                        fields=fields_from_evidence(cached_evidence, outcomes=cached_outcomes, source="cache"),
                        reason_code=cached_evidence.gap or "stale",
                        last_success_at=cached_evidence.fetched_at,
                        implication=cached_evidence.implication,
                        scenario="complete" if cached_evidence.complete() else "partial",
                        source="cache",
                        gap=cached_evidence.gap,
                        missing_fields=missing if cached_evidence.gap else [],
                    )
                    continue
                symbols[symbol] = symbol_health(
                    symbol,
                    asset_class="stocks",
                    supported=True,
                    fields=empty_fields(reason_code="stale", source="none", fetched_at=fetched_at),
                    reason_code="stale",
                    source="none",
                    scenario="deferred",
                    next_retry=next_retry_at("stale", now=fetched_at),
                )
            except Exception:
                symbols[symbol] = symbol_health(
                    symbol,
                    asset_class="stocks",
                    supported=True,
                    fields=empty_fields(reason_code="query_error", fetched_at=fetched_at),
                    reason_code="query_error",
                    source="none",
                    scenario="isolated_failure",
                    next_retry=next_retry_at("query_error", now=fetched_at),
                )
        report = {
            "live": True,
            "data_class": "live_current",
            "as_of": fetched_at,
            "budget": {"max_calls": budget, "used": used, "next_retry_at": next_retry_at("rate_limited", now=fetched_at)},
            "symbols": symbols,
            "note": "Live-current coverage only. Cache fallback is last success, not an inferred fill.",
        }
        persist_health(report)
        self._last_report = report
        return rows

    def discover(self) -> list[EventDocument]:
        mode = events_data_mode(self.settings)
        universe = resolve_watchlist(self.settings)
        if mode in {"demo", "fixture"}:
            if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("STOCK_PM_EARNINGS_FIXTURE") != "1":
                return []
            reset_earnings_registry()
            reset_earnings_health()
            try:
                from .earnings import load_frozen_coverage

                rows = load_frozen_coverage_documents()
                apply_frozen_health(load_frozen_coverage(), stocks=universe["stocks"], etfs=universe["etfs"])
            except Exception:
                rows = load_frozen_earnings_documents()
            rows.extend(local_degraded_earnings_documents())
            return rows
        if mode not in {"empty", "live"}:
            return []
        if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("STOCK_PM_EARNINGS_LIVE") != "1":
            return []
        reset_earnings_registry()
        return self._discover_live()


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


def reset_earnings_runtime() -> None:
    reset_earnings_registry()
    reset_sec_atom_cache()
    reset_earnings_health()
    reset_earnings_inject()
