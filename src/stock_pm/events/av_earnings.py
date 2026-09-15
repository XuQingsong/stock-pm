"""Alpha Vantage earnings prints. Reuses ALPHA_VANTAGE_API_KEY; keys never stored."""

from __future__ import annotations

import os
from collections import deque
from typing import Any
from urllib.parse import urlencode

from stock_pm.config import Settings
from stock_pm.fetch import FetchError, FetchResult, json_get, read_cache, utc_now

from .bodies import is_allowed_sec_host
from .earnings import (
    AV_EARNINGS_SOURCE,
    AV_ESTIMATES_SOURCE,
    EPS_UNIT,
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
    period_month_key,
    reset_earnings_registry,
)
from .earnings_health import (
    CACHE_TTL,
    attempted_symbols,
    clear_earnings_health_memory,
    current_earnings_health,
    empty_endpoints,
    empty_fields,
    endpoint_coverage,
    endpoint_record,
    field_record,
    fields_from_evidence,
    injected_reason,
    merge_endpoints,
    next_retry_at,
    parse_inject_env,
    persist_health,
    prioritize_endpoint_tasks,
    prioritize_symbols,
    purge_earnings_health_persist,
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


def _cache_fallback_reason(result: FetchResult) -> str:
    cause = result.cause or result.reason_code or "stale"
    if cause == "timeout":
        return "query_error"
    if cause in {"rate_limited", "query_error", "stale"}:
        return cause
    return "stale"


def fetch_av_function(function: str, symbol: str, *, settings: Settings | None = None, extra: dict[str, str] | None = None) -> FetchResult:
    """Return the raw FetchResult. Cache fallbacks keep from_cache/fetched_at/cause."""
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
        raise FetchError("rate_limited", "Alpha Vantage earnings rate limited")
    if payload.get("Error Message"):
        raise FetchError("unsupported", "Alpha Vantage earnings query is not supported for this symbol")
    return result


def _result_from_av_fetch(raw: Any) -> FetchResult:
    """Accept FetchResult or a test-double payload dict (treated as live)."""
    if isinstance(raw, FetchResult):
        return raw
    if isinstance(raw, dict):
        return FetchResult(
            payload=raw,
            status="ok",
            reason_code="within_threshold",
            fetched_at="",
            from_cache=False,
        )
    raise FetchError("record_invalid", "Alpha Vantage earnings payload is not an object")


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


def _issuer_cik(symbol: str) -> str:
    try:
        from stock_pm.research.issuer import cik_for

        return cik_for(symbol) or WATCH_CIKS.get(symbol.upper(), "")
    except Exception:
        return WATCH_CIKS.get(symbol.upper(), "")


def sec_company_8k_url(symbol: str) -> str:
    """Company 8-K search page. Not a citation of a specific earnings print."""
    cik = _issuer_cik(symbol)
    if not cik:
        return ""
    return f"{SEC_COMPANY_ATOM}?action=getcompany&CIK={cik}&type=8-K&owner=include&count=8"


def company_8k_atom_url(symbol: str) -> str:
    cik = _issuer_cik(symbol)
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
    return prioritize_symbols(stocks, previous)


def _prioritize_endpoint_tasks(stocks: list[str], previous: dict[str, Any]) -> list[tuple[str, str]]:
    return prioritize_endpoint_tasks(stocks, previous)


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
    ) -> tuple[dict[str, Any] | None, str | None, str, str | None]:
        inject = injected_reason(symbol, function)
        if inject:
            cached = read_av_cache(function, symbol, extra)
            if inject in {"rate_limited", "query_error"} and cached:
                return cached["payload"], inject, "cache", str(cached.get("fetched_at") or "") or None
            return None, inject, "none", None
        try:
            result = _result_from_av_fetch(fetch_av_function(function, symbol, settings=self.settings, extra=extra))
            payload = result.payload if isinstance(result.payload, dict) else None
            if payload is None:
                return None, "record_invalid", "none", None
            if result.from_cache:
                reason = _cache_fallback_reason(result)
                return payload, reason, "cache", str(result.fetched_at or "") or None
            return payload, None, "live", None
        except FetchError as exc:
            cached = read_av_cache(function, symbol, extra)
            if cached:
                reason = exc.reason_code if exc.reason_code in {"rate_limited", "query_error", "stale"} else "stale"
                return cached["payload"], reason, "cache", str(cached.get("fetched_at") or "") or None
            return None, exc.reason_code, "none", None
        except Exception:
            cached = read_av_cache(function, symbol, extra)
            if cached:
                return cached["payload"], "stale", "cache", str(cached.get("fetched_at") or "") or None
            return None, "query_error", "none", None

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
        judged_earn = evaluate_av_endpoint("EARNINGS", cached["payload"], symbol=symbol, fetched_at=fetched_at)
        if not judged_earn["usable"]:
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
            judged_est = evaluate_av_endpoint(
                "EARNINGS_ESTIMATES",
                estimates_cached["payload"],
                symbol=symbol,
                quarter=judged_earn["quarter"],
                fetched_at=fetched_at,
            )
            outcomes["EARNINGS_ESTIMATES"] = {
                "reason_code": None if judged_est["usable"] else (judged_est["reason_code"] or "stale"),
                "source": "cache" if judged_est["usable"] else "none",
                "fetched_at": str(estimates_cached.get("fetched_at") or fetched_at),
                "last_success_at": str(estimates_cached.get("fetched_at") or fetched_at) if judged_est["usable"] else None,
            }
            if not judged_est["usable"]:
                estimates = None
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
                judged_tr = evaluate_av_endpoint(
                    "EARNINGS_CALL_TRANSCRIPT",
                    tr_cached["payload"],
                    symbol=symbol,
                    quarter=quarter,
                    fetched_at=fetched_at,
                )
                outcomes["EARNINGS_CALL_TRANSCRIPT"] = {
                    "reason_code": None if judged_tr["usable"] else (judged_tr["reason_code"] or "stale"),
                    "source": "cache" if judged_tr["usable"] else "none",
                    "fetched_at": str(tr_cached.get("fetched_at") or fetched_at),
                    "last_success_at": str(tr_cached.get("fetched_at") or fetched_at) if judged_tr["usable"] else None,
                }
                if judged_tr["usable"]:
                    evidence = self._evidence_from_payload(
                        symbol,
                        cached["payload"],
                        fetched_at=str(cached.get("fetched_at") or fetched_at),
                        estimates=estimates,
                        transcript=tr_cached["payload"],
                        quarter=quarter,
                    )
        return evidence, outcomes

    def _health_from_evidence(
        self,
        symbol: str,
        evidence: Any,
        *,
        outcomes: dict[str, dict[str, Any]],
        source: str,
        last_attempt_at: str | None,
        this_round_calls: int,
        this_round: str,
        endpoints: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        missing = [
            name
            for name, attr in (("actual", "actual"), ("prior", "prior_year_actual"), ("consensus", "consensus"))
            if getattr(evidence, attr, None) is None
        ]
        if not evidence.transcript_excerpts:
            missing.append("transcript")
        earn = (endpoints or {}).get("EARNINGS") or {}
        last_success = (
            earn.get("last_success_at")
            or (outcomes.get("EARNINGS") or {}).get("last_success_at")
            or (evidence.fetched_at if source == "live" else None)
        )
        retries = [
            str(row.get("next_retry_at"))
            for row in (endpoints or {}).values()
            if isinstance(row, dict) and row.get("next_retry_at")
        ]
        return symbol_health(
            symbol,
            asset_class="stocks",
            supported=True,
            fields=fields_from_evidence(evidence, outcomes=outcomes, source=source),
            reason_code=evidence.gap or (outcomes.get("EARNINGS") or {}).get("reason_code"),
            last_success_at=last_success,
            next_retry=min(retries) if retries else None,
            implication=evidence.implication,
            scenario="complete" if evidence.complete() else "partial",
            source=source,
            gap=evidence.gap,
            missing_fields=missing if evidence.gap or "transcript" in missing else [],
            last_attempt_at=last_attempt_at,
            this_round_calls=this_round_calls,
            this_round=this_round,
            endpoints=endpoints,
        )

    def _quarter_from_payload(self, symbol: str, payload: dict[str, Any], fetched_at: str) -> str:
        try:
            quarters = parse_av_earnings(payload)
        except FetchError:
            return ""
        if not quarters:
            return ""
        preview = evidence_from_av_quarters(
            quarters,
            symbol=symbol,
            fetched_at=fetched_at,
            source_url=AV_EARNINGS_SOURCE.format(symbol=symbol),
        )
        return preview.fiscal_quarter or fiscal_quarter_id(symbol, preview.fiscal_date_ending)

    def _seed_bundle(self, symbol: str, previous_row: dict[str, Any], fetched_at: str) -> dict[str, Any]:
        prev_eps = (previous_row or {}).get("endpoints") or {}
        quarter = str((prev_eps.get("EARNINGS") or {}).get("quarter") or "")
        cached_earn = read_av_cache("EARNINGS", symbol)
        payload = None
        source = None
        if cached_earn:
            judged = evaluate_av_endpoint(
                "EARNINGS", cached_earn["payload"], symbol=symbol, fetched_at=fetched_at
            )
            if judged["usable"]:
                payload = cached_earn["payload"]
                source = "cache"
                quarter = quarter or judged["quarter"]
        return {
            "payload": payload,
            "earnings_source": source,
            "estimates": None,
            "transcript": None,
            "quarter": quarter,
        }

    def _record_endpoint(
        self,
        *,
        previous_row: dict[str, Any],
        updates: dict[str, dict[str, Any]],
        endpoint: str,
        fetched_at: str,
        reason: str | None,
        source: str,
        payload: dict[str, Any] | None,
        quarter: str = "",
        period: str = "",
        usable: bool = False,
        this_round: bool,
        attempted: bool,
        observed_at: str | None = None,
    ) -> None:
        prev = ((previous_row or {}).get("endpoints") or {}).get(endpoint) or {}
        live_success = (
            usable
            and source == "live"
            and reason not in {"rate_limited", "stale", "query_error"}
        )
        cache_usable = bool(usable) and not live_success
        if live_success:
            status = "ok"
            success = fetched_at
            retry = None
        elif cache_usable:
            status = "stale"
            success = observed_at or prev.get("last_success_at")
            retry = next_retry_at(reason or "stale", now=fetched_at) if attempted else prev.get("next_retry_at")
        elif reason == "skipped_dependency":
            status = "skipped_dependency"
            success = None
            retry = next_retry_at(reason, now=fetched_at) if attempted or reason else prev.get("next_retry_at")
        elif attempted:
            status = "failed"
            prior_ok = prev.get("status") in {"ok", "stale"} and prev.get("last_success_at")
            success = prev.get("last_success_at") if prior_ok else None
            retry = next_retry_at(reason or status, now=fetched_at)
        else:
            status = str(prev.get("status") or "pending")
            success = prev.get("last_success_at") if prev.get("status") in {"ok", "stale"} else None
            retry = prev.get("next_retry_at")
        updates[endpoint] = endpoint_record(
            status=status,
            last_attempt_at=fetched_at if attempted else prev.get("last_attempt_at"),
            last_success_at=success if status in {"ok", "stale"} else None,
            reason_code=reason,
            source=source if usable or reason else str(prev.get("source") or "none"),
            quarter=(
                quarter
                if usable
                else (str(prev.get("quarter") or "") if success else "")
            ),
            period=(
                period
                if usable
                else (str(prev.get("period") or "") if success else "")
            ),
            this_round=this_round,
            next_retry=retry,
        )

    def _deferred_health(self, symbol: str, previous_row: dict[str, Any], fetched_at: str) -> tuple[Any | None, dict[str, Any]]:
        cached_evidence, cached_outcomes = self._symbol_from_cache(symbol, fetched_at)
        endpoints = merge_endpoints((previous_row or {}).get("endpoints"))
        skipped = (endpoints.get("EARNINGS_CALL_TRANSCRIPT") or {})
        if skipped.get("status") == "skipped_dependency" or skipped.get("reason_code") == "skipped_dependency":
            cached_outcomes["EARNINGS_CALL_TRANSCRIPT"] = {
                "reason_code": "skipped_dependency",
                "source": "none",
                "fetched_at": fetched_at,
                "last_success_at": None,
            }
        if cached_evidence is not None:
            row = self._health_from_evidence(
                symbol,
                cached_evidence,
                outcomes=cached_outcomes,
                source="cache",
                last_attempt_at=previous_row.get("last_attempt_at"),
                this_round_calls=0,
                this_round="deferred",
                endpoints=endpoints,
            )
            row["scenario"] = "deferred"
            return cached_evidence, row
        if previous_row:
            carried = dict(previous_row)
            carried["this_round"] = "deferred"
            carried["this_round_calls"] = 0
            carried["scenario"] = previous_row.get("scenario") or "deferred"
            carried["endpoints"] = endpoints
            return None, carried
        return None, symbol_health(
            symbol,
            asset_class="stocks",
            supported=True,
            fields=empty_fields(reason_code="stale", source="none", fetched_at=fetched_at),
            reason_code="stale",
            source="none",
            scenario="deferred",
            next_retry=next_retry_at("stale", now=fetched_at),
            last_attempt_at=None,
            this_round_calls=0,
            this_round="deferred",
            endpoints=empty_endpoints(),
        )

    def _discover_live(self) -> list[EventDocument]:
        parse_inject_env()
        universe = resolve_watchlist(self.settings)
        stocks = universe["stocks"]
        etfs = universe["etfs"]
        fetched_at = utc_now()
        previous = current_earnings_health()
        previous_rows = previous.get("symbols") or {}
        budget = _budget(self.settings)
        used = 0
        rows: list[EventDocument] = []
        symbols: dict[str, Any] = {}
        round_calls: dict[str, int] = {}
        bundles: dict[str, dict[str, Any]] = {
            symbol: self._seed_bundle(symbol, previous_rows.get(symbol) or {}, fetched_at) for symbol in stocks
        }
        outcomes_by: dict[str, dict[str, dict[str, Any]]] = {}
        endpoint_updates: dict[str, dict[str, dict[str, Any]]] = {symbol: {} for symbol in stocks}
        attempted_tasks: list[dict[str, str]] = []

        def bump(symbol: str, n: int = 1) -> None:
            nonlocal used
            used += n
            round_calls[symbol] = round_calls.get(symbol, 0) + n

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
                    this_round="not_configured",
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
                    this_round="unsupported",
                )
            report = {
                "live": False,
                "data_class": "live_current",
                "as_of": fetched_at,
                "budget": {"max_calls": budget, "used": 0},
                "schedule": {"next_symbol": stocks[0] if stocks else None, "next_task": None, "attempted_this_round": []},
                "endpoints": endpoint_coverage({"symbols": symbols, "schedule": {"attempted_this_round": []}}),
                "cache_ttl": CACHE_TTL,
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
                last_attempt_at=fetched_at,
                this_round="unsupported",
            )

        for symbol in stocks:
            prev = previous_rows.get(symbol) or {}
            earn_prev = ((prev.get("endpoints") or {}).get("EARNINGS") or {})
            if (
                (earn_prev.get("last_attempt_at") or earn_prev.get("last_success_at") or prev.get("last_attempt_at"))
                and not bundles[symbol]["quarter"]
            ):
                self._record_endpoint(
                    previous_row=prev,
                    updates=endpoint_updates[symbol],
                    endpoint="EARNINGS_CALL_TRANSCRIPT",
                    fetched_at=fetched_at,
                    reason="skipped_dependency",
                    source="none",
                    payload=None,
                    this_round=False,
                    attempted=False,
                )
                outcomes_by.setdefault(symbol, {})["EARNINGS_CALL_TRANSCRIPT"] = {
                    "reason_code": "skipped_dependency",
                    "source": "none",
                    "fetched_at": fetched_at,
                    "last_success_at": None,
                }

        queue = deque(_prioritize_endpoint_tasks(stocks, previous))
        queued = set(queue)
        while queue:
            if used >= budget:
                break
            symbol, endpoint = queue.popleft()
            if symbol in symbols:
                continue
            if injected_reason(symbol) == "unsupported":
                symbols[symbol] = symbol_health(
                    symbol,
                    asset_class="stocks",
                    supported=False,
                    fields=empty_fields(reason_code="unsupported", fetched_at=fetched_at),
                    reason_code="unsupported",
                    source="none",
                    scenario="unsupported",
                    last_attempt_at=fetched_at,
                    this_round_calls=0,
                    this_round="unsupported",
                )
                continue
            extra = None
            if endpoint == "EARNINGS_CALL_TRANSCRIPT":
                quarter = str(bundles[symbol].get("quarter") or "")
                if not quarter:
                    self._record_endpoint(
                        previous_row=previous_rows.get(symbol) or {},
                        updates=endpoint_updates[symbol],
                        endpoint=endpoint,
                        fetched_at=fetched_at,
                        reason="skipped_dependency",
                        source="none",
                        payload=None,
                        this_round=True,
                        attempted=False,
                    )
                    outcomes_by.setdefault(symbol, {})[endpoint] = {
                        "reason_code": "skipped_dependency",
                        "source": "none",
                        "fetched_at": fetched_at,
                        "last_success_at": None,
                    }
                    continue
                extra = {"quarter": quarter}
            payload, err, src, observed_at = self._fetch_isolated(endpoint, symbol, extra=extra)
            bump(symbol, 1)
            attempted_tasks.append({"symbol": symbol, "endpoint": endpoint})
            quarter = str(bundles[symbol].get("quarter") or "")
            judged = evaluate_av_endpoint(
                endpoint, payload, symbol=symbol, quarter=quarter, fetched_at=observed_at or fetched_at
            )
            usable = bool(judged["usable"])
            if not err:
                err = judged["reason_code"]
            elif usable and err in {"rate_limited", "stale", "query_error"}:
                pass
            elif not usable and not judged["reason_code"]:
                err = err or "upstream_empty"
            if not usable and err in {None, ""}:
                err = judged["reason_code"] or "upstream_empty"
            live_ok = usable and src == "live" and err not in {"rate_limited", "stale", "query_error"}
            success_at = fetched_at if live_ok else (observed_at if usable else None)
            retry_at = None if live_ok else next_retry_at(err or "stale", now=fetched_at)
            outcomes_by.setdefault(symbol, {})[endpoint] = {
                "reason_code": err,
                "source": src if usable or payload else "none",
                "fetched_at": observed_at if src == "cache" else fetched_at,
                "last_success_at": success_at,
                "next_retry_at": retry_at,
            }
            period = str(judged.get("period") or "")
            if endpoint == "EARNINGS":
                if usable and payload:
                    bundles[symbol]["payload"] = payload
                    bundles[symbol]["earnings_source"] = src
                    quarter = judged["quarter"] or self._quarter_from_payload(symbol, payload, fetched_at)
                    bundles[symbol]["quarter"] = quarter
                else:
                    quarter = ""
                    bundles[symbol]["quarter"] = ""
                if not quarter:
                    self._record_endpoint(
                        previous_row=previous_rows.get(symbol) or {},
                        updates=endpoint_updates[symbol],
                        endpoint="EARNINGS_CALL_TRANSCRIPT",
                        fetched_at=fetched_at,
                        reason="skipped_dependency",
                        source="none",
                        payload=None,
                        usable=False,
                        this_round=True,
                        attempted=False,
                    )
                    outcomes_by.setdefault(symbol, {})["EARNINGS_CALL_TRANSCRIPT"] = {
                        "reason_code": "skipped_dependency",
                        "source": "none",
                        "fetched_at": fetched_at,
                        "last_success_at": None,
                    }
            elif endpoint == "EARNINGS_ESTIMATES":
                bundles[symbol]["estimates"] = payload if usable else payload
            else:
                bundles[symbol]["transcript"] = payload if usable else payload
            self._record_endpoint(
                previous_row=previous_rows.get(symbol) or {},
                updates=endpoint_updates[symbol],
                endpoint=endpoint,
                fetched_at=fetched_at,
                reason=err,
                source=src,
                payload=payload,
                quarter=quarter if endpoint == "EARNINGS" else bundles[symbol].get("quarter") or "",
                period=period,
                usable=usable,
                this_round=True,
                attempted=True,
                observed_at=observed_at,
            )
            if endpoint == "EARNINGS" and usable:
                if quarter:
                    skipped = endpoint_updates[symbol].get("EARNINGS_CALL_TRANSCRIPT") or {}
                    if skipped.get("status") == "skipped_dependency":
                        endpoint_updates[symbol]["EARNINGS_CALL_TRANSCRIPT"] = endpoint_record(status="pending")
                        outcomes_by.get(symbol, {}).pop("EARNINGS_CALL_TRANSCRIPT", None)
                    nxt = (symbol, "EARNINGS_CALL_TRANSCRIPT")
                    if nxt not in queued:
                        queue.append(nxt)
                        queued.add(nxt)
                nxt_est = (symbol, "EARNINGS_ESTIMATES")
                if nxt_est not in queued:
                    queue.append(nxt_est)
                    queued.add(nxt_est)

        attempted_set = {(item["symbol"], item["endpoint"]) for item in attempted_tasks}
        remaining_tasks = [task for task in queue if task not in attempted_set]
        next_task = {"symbol": remaining_tasks[0][0], "endpoint": remaining_tasks[0][1]} if remaining_tasks else None

        for symbol in stocks:
            if symbol in symbols:
                continue
            prev = previous_rows.get(symbol) or {}
            endpoints = merge_endpoints(prev.get("endpoints"), endpoint_updates.get(symbol))
            if round_calls.get(symbol, 0) <= 0:
                evidence, row = self._deferred_health(symbol, prev, fetched_at)
                row["endpoints"] = endpoints
                if evidence is not None:
                    rows.extend(documents_from_evidence(evidence))
                symbols[symbol] = row
                continue
            bundle = bundles.get(symbol) or {}
            outcomes = dict(outcomes_by.get(symbol) or {})
            for name, rec in endpoints.items():
                if not isinstance(rec, dict) or not rec.get("last_success_at"):
                    continue
                existing = dict(outcomes.get(name) or {})
                if not existing.get("last_success_at"):
                    existing["last_success_at"] = rec.get("last_success_at")
                if not existing.get("fetched_at"):
                    existing["fetched_at"] = rec.get("last_success_at")
                if not existing.get("source"):
                    existing["source"] = rec.get("source") or "none"
                if existing.get("next_retry_at") is None:
                    existing["next_retry_at"] = rec.get("next_retry_at")
                outcomes[name] = existing
            live_source = str(bundle.get("earnings_source") or (outcomes.get("EARNINGS") or {}).get("source") or "none")
            evidence = None
            if bundle.get("payload"):
                if bundle.get("estimates") is None:
                    cached_est = read_av_cache("EARNINGS_ESTIMATES", symbol)
                    if cached_est:
                        judged_est = evaluate_av_endpoint(
                            "EARNINGS_ESTIMATES",
                            cached_est["payload"],
                            symbol=symbol,
                            quarter=str(bundle.get("quarter") or ""),
                            fetched_at=fetched_at,
                        )
                        bundle["estimates"] = cached_est["payload"]
                        outcomes.setdefault("EARNINGS_ESTIMATES", {
                            "reason_code": None if judged_est["usable"] else (judged_est["reason_code"] or "stale"),
                            "source": "cache" if judged_est["usable"] else "none",
                            "fetched_at": str(cached_est.get("fetched_at") or fetched_at),
                            "last_success_at": str(cached_est.get("fetched_at") or fetched_at) if judged_est["usable"] else None,
                        })
                if bundle.get("transcript") is None and bundle.get("quarter"):
                    cached_tr = read_av_cache("EARNINGS_CALL_TRANSCRIPT", symbol, {"quarter": bundle["quarter"]})
                    if cached_tr:
                        judged_tr = evaluate_av_endpoint(
                            "EARNINGS_CALL_TRANSCRIPT",
                            cached_tr["payload"],
                            symbol=symbol,
                            quarter=str(bundle.get("quarter") or ""),
                            fetched_at=fetched_at,
                        )
                        bundle["transcript"] = cached_tr["payload"]
                        outcomes.setdefault("EARNINGS_CALL_TRANSCRIPT", {
                            "reason_code": None if judged_tr["usable"] else (judged_tr["reason_code"] or "stale"),
                            "source": "cache" if judged_tr["usable"] else "none",
                            "fetched_at": str(cached_tr.get("fetched_at") or fetched_at),
                            "last_success_at": str(cached_tr.get("fetched_at") or fetched_at) if judged_tr["usable"] else None,
                        })
                earn_out = outcomes.get("EARNINGS") or {}
                earn_ep = endpoints.get("EARNINGS") or {}
                evidence_at = str(
                    earn_out.get("last_success_at")
                    or earn_ep.get("last_success_at")
                    or earn_out.get("fetched_at")
                    or fetched_at
                )
                evidence = self._evidence_from_payload(
                    symbol,
                    bundle["payload"],
                    fetched_at=evidence_at,
                    estimates=bundle.get("estimates"),
                    transcript=bundle.get("transcript"),
                    quarter=bundle.get("quarter") or "",
                )
            if evidence is None:
                cached_evidence, cached_outcomes = self._symbol_from_cache(symbol, fetched_at)
                evidence = cached_evidence
                if cached_outcomes:
                    for key, value in cached_outcomes.items():
                        outcomes.setdefault(key, value)
                    live_source = "cache"
            if (endpoints.get("EARNINGS_CALL_TRANSCRIPT") or {}).get("status") == "skipped_dependency":
                outcomes.setdefault(
                    "EARNINGS_CALL_TRANSCRIPT",
                    {"reason_code": "skipped_dependency", "source": "none", "fetched_at": fetched_at, "last_success_at": None},
                )
            if evidence is None:
                reason = (outcomes.get("EARNINGS") or {}).get("reason_code") or "upstream_empty"
                fields = empty_fields(reason_code=reason, source=live_source, fetched_at=fetched_at)
                if (outcomes.get("EARNINGS_CALL_TRANSCRIPT") or {}).get("reason_code") == "skipped_dependency":
                    fields["transcript"] = field_record(
                        status="missing",
                        reason_code="skipped_dependency",
                        fetched_at=fetched_at,
                        source="none",
                    )
                symbols[symbol] = symbol_health(
                    symbol,
                    asset_class="stocks",
                    supported=reason != "unsupported",
                    fields=fields,
                    reason_code=reason,
                    source=live_source,
                    scenario="partial" if reason != "unsupported" else "unsupported",
                    next_retry=next_retry_at(reason, now=fetched_at),
                    last_attempt_at=fetched_at,
                    this_round_calls=round_calls.get(symbol, 0),
                    this_round="live" if round_calls.get(symbol) else "cache",
                    endpoints=endpoints,
                )
                continue
            rows.extend(documents_from_evidence(evidence))
            if any((outcomes.get(name) or {}).get("source") == "live" for name in ("EARNINGS", "EARNINGS_ESTIMATES", "EARNINGS_CALL_TRANSCRIPT")):
                live_source = live_source if live_source in {"live", "cache"} else "live"
            symbols[symbol] = self._health_from_evidence(
                symbol,
                evidence,
                outcomes=outcomes,
                source=live_source,
                last_attempt_at=fetched_at,
                this_round_calls=round_calls.get(symbol, 0),
                this_round="live" if round_calls.get(symbol) else "cache",
                endpoints=endpoints,
            )

        deferred = [symbol for symbol in stocks if not round_calls.get(symbol)]
        report = {
            "live": True,
            "data_class": "live_current",
            "as_of": fetched_at,
            "budget": {
                "max_calls": budget,
                "used": used,
                "this_round": dict(round_calls),
                "deferred": deferred,
                "next_retry_at": next_retry_at("rate_limited", now=fetched_at),
            },
            "schedule": {
                "next_symbol": (next_task or {}).get("symbol") if next_task else (stocks[0] if stocks else None),
                "next_task": next_task,
                "attempted_this_round": list(attempted_tasks),
                "attempted_symbols_this_round": attempted_symbols(attempted_tasks),
                "round": int((previous.get("schedule") or {}).get("round") or 0) + 1,
            },
            "cache_ttl": CACHE_TTL,
            "symbols": symbols,
            "note": "Live-current coverage only. Cache/stale complete is not this-round live complete. Endpoints rotate independently after fresh EARNINGS.",
        }
        report["endpoints"] = endpoint_coverage(report)
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
            clear_earnings_health_memory()
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


def _next_fiscal_quarter(quarter: str) -> str:
    raw = str(quarter or "")
    if "Q" not in raw:
        return ""
    year_text, _, q_text = raw.partition("Q")
    try:
        year = int(year_text)
        qn = int(q_text)
    except ValueError:
        return ""
    if qn >= 4:
        return f"{year + 1}Q1"
    return f"{year}Q{qn + 1}"


def _estimate_number(row: dict[str, Any]) -> float | None:
    for key in ("eps_estimate_average", "estimatedEPS", "consensus", "eps"):
        value = parse_number(row.get(key))
        if value is not None:
            return value
    return None


def _estimate_unit_currency_ok(row: dict[str, Any]) -> bool:
    unit = str(row.get("unit") or EPS_UNIT).strip()
    currency = str(row.get("currency") or "USD").strip().upper()
    if unit and unit not in {EPS_UNIT, "USD/share", "eps"}:
        return False
    return currency in {"", "USD"}


def evaluate_av_endpoint(
    endpoint: str,
    payload: dict[str, Any] | None,
    *,
    symbol: str = "",
    quarter: str = "",
    fetched_at: str = "",
) -> dict[str, Any]:
    """Semantic success only. A non-empty dict is not last-success."""
    empty = {"usable": False, "reason_code": "upstream_empty", "quarter": "", "period": ""}
    if not isinstance(payload, dict):
        return {**empty, "reason_code": "record_invalid" if payload is not None else "upstream_empty"}
    if endpoint == "EARNINGS":
        try:
            rows = parse_av_earnings(payload)
        except FetchError as exc:
            return {**empty, "reason_code": exc.reason_code or "record_invalid"}
        if payload.get("quarterlyEarnings") is not None and not isinstance(payload.get("quarterlyEarnings"), list):
            return {**empty, "reason_code": "record_invalid"}
        if not rows:
            return empty
        preview = evidence_from_av_quarters(
            rows,
            symbol=symbol,
            fetched_at=fetched_at or utc_now(),
            source_url=AV_EARNINGS_SOURCE.format(symbol=symbol or "UNKNOWN"),
        )
        qid = preview.fiscal_quarter or fiscal_quarter_id(symbol, preview.fiscal_date_ending)
        period = preview.fiscal_date_ending or period_month_key(preview.fiscal_date_ending)
        if not period and not qid:
            return {**empty, "reason_code": "record_invalid"}
        return {"usable": True, "reason_code": None, "quarter": qid, "period": period}
    if endpoint == "EARNINGS_ESTIMATES":
        try:
            rows = parse_av_estimates(payload)
        except FetchError as exc:
            return {**empty, "reason_code": exc.reason_code or "record_invalid"}
        if not rows:
            return empty
        mismatch = False
        for row in rows:
            if _estimate_number(row) is None:
                continue
            if not _estimate_unit_currency_ok(row):
                mismatch = True
                continue
            horizon = str(row.get("horizon") or "").lower()
            if "historical" in horizon:
                continue
            item_date = str(row.get("date") or row.get("fiscalDateEnding") or "")
            item_q = fiscal_quarter_id(symbol, item_date) if item_date else ""
            if quarter and item_q and item_q != quarter and item_q != _next_fiscal_quarter(quarter) and "next" not in horizon:
                mismatch = True
                continue
            if quarter and item_q == quarter:
                return {"usable": True, "reason_code": None, "quarter": quarter, "period": item_date}
            if "next" in horizon or (quarter and item_q == _next_fiscal_quarter(quarter)):
                return {"usable": True, "reason_code": None, "quarter": quarter or item_q, "period": item_date}
            if not quarter and (item_q or item_date):
                return {"usable": True, "reason_code": None, "quarter": item_q, "period": item_date}
            if quarter and not item_q and "current" in horizon:
                return {"usable": True, "reason_code": None, "quarter": quarter, "period": item_date}
        return {**empty, "reason_code": "period_mismatch" if mismatch else "upstream_empty"}
    if endpoint == "EARNINGS_CALL_TRANSCRIPT":
        rows = payload.get("transcript")
        if rows is None:
            rows = payload.get("excerpts")
        if rows is None:
            return empty
        if not isinstance(rows, list):
            return {**empty, "reason_code": "record_invalid"}
        payload_q = str(payload.get("quarter") or "")
        if quarter and payload_q and payload_q != quarter:
            return {**empty, "reason_code": "period_mismatch"}
        mismatch = bool(quarter and payload_q and payload_q != quarter)
        usable_text = False
        for item in rows:
            if not isinstance(item, dict):
                continue
            text = str(item.get("content") or item.get("excerpt") or "").strip()
            item_q = str(item.get("quarter") or payload_q or quarter or "")
            if quarter and item_q and item_q != quarter:
                mismatch = True
                continue
            if text:
                usable_text = True
        if usable_text:
            return {"usable": True, "reason_code": None, "quarter": quarter or payload_q, "period": quarter or payload_q}
        return {**empty, "reason_code": "period_mismatch" if mismatch else "upstream_empty"}
    return {**empty, "reason_code": "record_invalid"}


def reset_earnings_runtime() -> None:
    reset_earnings_registry()
    reset_sec_atom_cache()
    purge_earnings_health_persist()
    reset_earnings_inject()
