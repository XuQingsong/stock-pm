"""Discovery and reference clients. Tavily/Exa are not the publisher."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from stock_pm.config import Settings
from stock_pm.fetch import FetchError, json_get, json_post
from stock_pm.research.ids import new_id
from stock_pm.research.official import document_text, fetch_html, web_search
from stock_pm.series import fetch_fred_series, parse_fred_observations

from .quality import canonical_url, host_of, source_family, source_tier, source_type_for


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _cutoff(days: int) -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=days)


def parse_published(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 8 and text[:8].isdigit() and "T" in text:
        # Alpha Vantage: 20260916T183000
        compact = text.replace("T", "")[:14]
        try:
            stamp = datetime.strptime(compact[:8], "%Y%m%d")
            return stamp.date().isoformat()
        except ValueError:
            pass
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return stamp.date().isoformat()
    except ValueError:
        pass
    if len(text) >= 10:
        try:
            datetime.strptime(text[:10], "%Y-%m-%d")
            return text[:10]
        except ValueError:
            return None
    return None


def within_days(published: str | None, days: int) -> bool:
    if not published:
        return False
    try:
        stamp = datetime.strptime(published[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return stamp >= _cutoff(days)


def _clean(text: Any, *, limit: int = 24000) -> str:
    return " ".join(str(text or "").split())[:limit]


def _document(
    *,
    provider: str,
    url: str,
    title: str,
    ticker: str | None,
    query: str,
    query_type: str,
    published_at: str | None,
    raw_text: str,
    clean_text: str,
    score: float | None = None,
    author: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean = _clean(clean_text or raw_text)
    raw = _clean(raw_text or clean_text)
    full = len(clean) >= 400
    return {
        "document_id": new_id("xdoc"),
        "provider": provider,
        "source_type": source_type_for(url, query_type=query_type),
        "ticker": ticker,
        "title": title,
        "url": url,
        "canonical_url": canonical_url(url),
        "source_domain": host_of(url),
        "published_at": published_at,
        "fetched_at": _now(),
        "author": author,
        "raw_text": raw,
        "clean_text": clean,
        "provider_score": score,
        "is_full_text": full,
        "is_dated": bool(published_at),
        "is_primary_source": source_tier(url) == 1,
        "query": query,
        "query_type": query_type,
        "source_family": source_family(url),
        "source_tier": source_tier(url),
        "metadata": extra or {},
    }


class SearchBudget:
    def __init__(self, *, tavily: int = 10, exa: int = 10) -> None:
        self.tavily = tavily
        self.exa = exa

    def take(self, provider: str) -> bool:
        if provider == "tavily" and self.tavily > 0:
            self.tavily -= 1
            return True
        if provider == "exa" and self.exa > 0:
            self.exa -= 1
            return True
        return False


def tavily_configured(settings: Settings) -> bool:
    return bool((settings.tavily_api_key or "").strip())


def exa_configured(settings: Settings) -> bool:
    return bool((settings.exa_api_key or "").strip())


def tavily_search(
    query: str,
    *,
    settings: Settings,
    ticker: str | None,
    query_type: str,
    days: int,
    max_results: int = 5,
    topic: str = "news",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.perf_counter()
    topic_name = topic or "news"
    audit: dict[str, Any] = {
        "provider": "tavily",
        "query": query,
        "query_type": query_type,
        "status": "ok",
        "topic": topic_name,
        "role": "extract_and_news_supplement",
    }
    if not tavily_configured(settings):
        audit.update({"status": "not_configured", "hit_count": 0, "error": "TAVILY_API_KEY missing"})
        return [], audit
    try:
        result = json_post(
            "https://api.tavily.com/search",
            {
                "api_key": settings.tavily_api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": max_results,
                "include_raw_content": True,
                "days": days,
                "topic": topic_name,
            },
            timeout=35,
            retries=2,
        )
    except FetchError as exc:
        audit.update({"status": "failed", "error": exc.reason_code, "hit_count": 0, "latency_ms": int((time.perf_counter() - started) * 1000)})
        return [], audit
    rows: list[dict[str, Any]] = []
    for item in list((result.payload or {}).get("results") or [])[:max_results]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url.startswith("https://"):
            continue
        raw = str(item.get("raw_content") or "")
        # Tavily "content" is a search summary — keep only as discovery text, not evidence.
        summary = str(item.get("content") or "")
        published = parse_published(item.get("published_date") or item.get("published_at"))
        recovered = False
        if not published and raw:
            from .dates import recover_published_at

            published = recover_published_at(raw)
            recovered = bool(published)
        row = _document(
            provider="tavily",
            url=url,
            title=str(item.get("title") or ""),
            ticker=ticker,
            query=query,
            query_type=query_type,
            published_at=published,
            raw_text=raw,
            clean_text=raw or "",
            score=float(item.get("score") or 0) or None,
            extra={
                "tavily_summary": summary[:400],
                "discovery_only_summary": True,
                "tavily_topic": topic_name,
                "date_recovered": recovered,
            },
        )
        rows.append(row)
    dated = sum(1 for row in rows if row.get("is_dated"))
    audit.update(
        {
            "hit_count": len(rows),
            "usable_count": sum(1 for row in rows if row.get("url")),
            "high_quality_count": sum(1 for row in rows if int(row.get("source_tier") or 9) <= 2),
            "full_text_count": sum(1 for row in rows if row.get("is_full_text")),
            "dated_count": dated,
            "date_return_rate": round(dated / len(rows), 3) if rows else 0.0,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    )
    return rows, audit


def tavily_extract(urls: list[str], *, settings: Settings) -> dict[str, str]:
    if not tavily_configured(settings) or not urls:
        return {}
    try:
        result = json_post(
            "https://api.tavily.com/extract",
            {"api_key": settings.tavily_api_key, "urls": urls[:8]},
            timeout=40,
            retries=1,
        )
    except FetchError:
        return {}
    out: dict[str, str] = {}
    for item in list((result.payload or {}).get("results") or []):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        text = str(item.get("raw_content") or item.get("text") or "")
        if url and len(text) >= 120:
            out[canonical_url(url)] = _clean(text)
    return out


def exa_search(
    query: str,
    *,
    settings: Settings,
    ticker: str | None,
    query_type: str,
    days: int,
    max_results: int = 5,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.perf_counter()
    audit: dict[str, Any] = {"provider": "exa", "query": query, "query_type": query_type, "status": "ok"}
    if not exa_configured(settings):
        audit.update({"status": "not_configured", "hit_count": 0, "error": "EXA_API_KEY missing"})
        return [], audit
    start = (_cutoff(days)).date().isoformat()
    try:
        result = json_post(
            "https://api.exa.ai/search",
            {
                "query": query,
                "type": "auto",
                "numResults": max_results,
                "startPublishedDate": f"{start}T00:00:00.000Z",
                "contents": {"text": True, "highlights": True},
            },
            headers={"x-api-key": settings.exa_api_key},
            timeout=35,
            retries=2,
        )
    except FetchError as exc:
        audit.update({"status": "failed", "error": exc.reason_code, "hit_count": 0, "latency_ms": int((time.perf_counter() - started) * 1000)})
        return [], audit
    rows: list[dict[str, Any]] = []
    for item in list((result.payload or {}).get("results") or [])[:max_results]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url.startswith("https://"):
            continue
        text = str(item.get("text") or "")
        highlights = item.get("highlights") or []
        highlight_text = " ".join(str(part) for part in highlights if part)
        rows.append(
            _document(
                provider="exa",
                url=url,
                title=str(item.get("title") or ""),
                ticker=ticker,
                query=query,
                query_type=query_type,
                published_at=parse_published(item.get("publishedDate") or item.get("published_at")),
                raw_text=text,
                clean_text=text,
                score=float(item.get("score") or 0) or None,
                author=str(item.get("author") or "") or None,
                extra={"highlights": highlight_text[:600], "exa_id": item.get("id")},
            )
        )
    audit.update(
        {
            "hit_count": len(rows),
            "usable_count": sum(1 for row in rows if row.get("url")),
            "high_quality_count": sum(1 for row in rows if int(row.get("source_tier") or 9) <= 2),
            "full_text_count": sum(1 for row in rows if row.get("is_full_text")),
            "dated_count": sum(1 for row in rows if row.get("is_dated")),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    )
    return rows, audit


def alphavantage_news(
    ticker: str,
    *,
    settings: Settings,
    days: int,
    limit: int = 20,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.perf_counter()
    audit: dict[str, Any] = {"provider": "alpha_vantage", "query": f"NEWS_SENTIMENT {ticker}", "query_type": "company_news", "status": "ok"}
    key = (settings.alpha_vantage_api_key or "").strip()
    if not key:
        audit.update({"status": "not_configured", "hit_count": 0, "error": "ALPHA_VANTAGE_API_KEY missing"})
        return [], audit
    start = _cutoff(days).strftime("%Y%m%dT0000")
    url = "https://www.alphavantage.co/query?" + urlencode(
        {"function": "NEWS_SENTIMENT", "tickers": ticker.upper(), "limit": str(limit), "time_from": start, "apikey": key}
    )
    try:
        result = json_get(url, timeout=30, retries=2, cache_key=None)
    except FetchError as exc:
        audit.update({"status": "failed", "error": exc.reason_code, "hit_count": 0, "latency_ms": int((time.perf_counter() - started) * 1000)})
        return [], audit
    payload = result.payload if isinstance(result.payload, dict) else {}
    if payload.get("Note") or payload.get("Information"):
        audit.update({"status": "failed", "error": "rate_limited", "hit_count": 0})
        return [], audit
    rows: list[dict[str, Any]] = []
    for item in list(payload.get("feed") or [])[:limit]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url.startswith("https://"):
            continue
        summary = str(item.get("summary") or "")
        rows.append(
            _document(
                provider="alpha_vantage",
                url=url,
                title=str(item.get("title") or ""),
                ticker=ticker.upper(),
                query=f"{ticker} news",
                query_type="company_news",
                published_at=parse_published(item.get("time_published")),
                raw_text="",
                clean_text="",
                extra={"av_summary": summary[:400], "av_source": item.get("source"), "discovery_only_summary": True},
            )
        )
    audit.update(
        {
            "hit_count": len(rows),
            "usable_count": sum(1 for row in rows if row.get("url")),
            "high_quality_count": sum(1 for row in rows if int(row.get("source_tier") or 9) <= 2),
            "full_text_count": 0,
            "dated_count": sum(1 for row in rows if row.get("is_dated")),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    )
    return rows, audit


def alphavantage_overview(ticker: str, *, settings: Settings) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    key = (settings.alpha_vantage_api_key or "").strip()
    audit: dict[str, Any] = {"provider": "alpha_vantage", "query": f"OVERVIEW {ticker}", "query_type": "market_data", "status": "ok"}
    if not key:
        audit.update({"status": "not_configured", "error": "ALPHA_VANTAGE_API_KEY missing"})
        return None, audit
    url = "https://www.alphavantage.co/query?" + urlencode({"function": "OVERVIEW", "symbol": ticker.upper(), "apikey": key})
    try:
        result = json_get(url, timeout=25, retries=2, cache_key=None)
    except FetchError as exc:
        audit.update({"status": "failed", "error": exc.reason_code})
        return None, audit
    payload = result.payload if isinstance(result.payload, dict) else {}
    if not payload or payload.get("Note") or not payload.get("Symbol"):
        audit.update({"status": "failed", "error": "empty_or_limited"})
        return None, audit
    audit["hit_count"] = 1
    return payload, audit


def duckduckgo_search(
    query: str,
    *,
    ticker: str | None,
    query_type: str,
    days: int,
    limit: int = 5,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.perf_counter()
    audit: dict[str, Any] = {"provider": "duckduckgo", "query": query, "query_type": query_type, "status": "ok"}
    try:
        hits = web_search(query, limit=limit)
    except Exception as exc:
        audit.update({"status": "failed", "error": str(exc)[:160], "hit_count": 0})
        return [], audit
    rows: list[dict[str, Any]] = []
    for item in hits or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        if not url.startswith("https://"):
            continue
        published = parse_published(item.get("published_at") or item.get("date") or item.get("title") or item.get("snippet"))
        if not published:
            from stock_pm.brain.news import _extract_published_at

            published = _extract_published_at(item.get("published_at"), item.get("date"), item.get("title"), item.get("snippet"))
        rows.append(
            _document(
                provider="duckduckgo",
                url=url,
                title=str(item.get("title") or ""),
                ticker=ticker,
                query=query,
                query_type=query_type,
                published_at=published,
                raw_text="",
                clean_text="",
                extra={"ddg_snippet": str(item.get("snippet") or "")[:400], "discovery_only_summary": True},
            )
        )
    audit.update(
        {
            "hit_count": len(rows),
            "usable_count": len(rows),
            "high_quality_count": sum(1 for row in rows if int(row.get("source_tier") or 9) <= 2),
            "full_text_count": 0,
            "dated_count": sum(1 for row in rows if row.get("is_dated") and within_days(row.get("published_at"), days)),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    )
    return rows, audit


FRED_SERIES = (
    ("CPIAUCSL", "CPI-U"),
    ("CPILFESL", "Core CPI"),
    ("PCEPI", "PCE"),
    ("PCEPILFE", "Core PCE"),
    ("FEDFUNDS", "Fed Funds Rate"),
    ("DGS2", "2Y Treasury"),
    ("DGS10", "10Y Treasury"),
    ("UNRATE", "Unemployment rate"),
    ("PAYEMS", "Nonfarm payrolls"),
    ("BAMLC0A0CM", "IG credit OAS"),
    ("BAMLH0A0HYM2", "HY credit OAS"),
)


def fred_macro_documents(*, settings: Settings, ticker: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    audit: dict[str, Any] = {"provider": "fred", "query": "macro_series", "query_type": "macro", "status": "ok", "series": []}
    key = (settings.fred_api_key or "").strip()
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for series_id, name in FRED_SERIES:
        try:
            result = fetch_fred_series(series_id, key, limit=4)
            observations = parse_fred_observations(result.payload)
        except Exception as exc:
            errors.append(f"{series_id}:{exc}")
            audit["series"].append({"series_id": series_id, "status": "failed"})
            continue
        latest = observations[-1] if observations else None
        if not latest:
            audit["series"].append({"series_id": series_id, "status": "empty"})
            continue
        value = latest.get("value")
        observed = str(latest.get("period") or latest.get("date") or latest.get("observed_at") or "")[:10]
        fact = f"FRED {series_id} ({name}) latest value {value} as of {observed}."
        url = f"https://fred.stlouisfed.org/series/{series_id}"
        rows.append(
            _document(
                provider="fred",
                url=url,
                title=f"{name} ({series_id})",
                ticker=ticker,
                query=series_id,
                query_type="macro",
                published_at=parse_published(observed),
                raw_text=fact,
                clean_text=fact,
                extra={"series_id": series_id, "value": value, "transport": getattr(result, "transport", None)},
            )
        )
        audit["series"].append({"series_id": series_id, "status": "ok", "date": observed, "value": value})
    if not rows and errors:
        audit["status"] = "failed"
        audit["error"] = "; ".join(errors)[:240]
    elif not key:
        audit["status"] = "partial"
        audit["error"] = "FRED_API_KEY missing; used keyless CSV fallback where possible"
    audit["hit_count"] = len(rows)
    audit["usable_count"] = len(rows)
    audit["dated_count"] = len(rows)
    audit["full_text_count"] = len(rows)
    audit["high_quality_count"] = len(rows)
    return rows, audit


def _apply_recovered_date(row: dict[str, Any], html_or_text: str) -> None:
    if row.get("published_at") or not html_or_text:
        return
    from .dates import recover_published_at

    found = recover_published_at(html_or_text)
    if not found:
        return
    row["published_at"] = found
    row["is_dated"] = True
    meta = dict(row.get("metadata") or {})
    meta["date_recovered"] = True
    row["metadata"] = meta


def fill_missing_bodies(rows: list[dict[str, Any]], *, settings: Settings, limit: int = 8) -> list[dict[str, Any]]:
    need = sorted(
        [row for row in rows if not row.get("is_full_text") and row.get("url") and int(row.get("source_tier") or 9) <= 4],
        key=lambda row: (int(row.get("source_tier") or 9), 0 if row.get("is_primary_source") else 1),
    )
    targets = {canonical_url(row.get("url")) for row in need[:limit]}
    extracted = tavily_extract([str(row.get("url")) for row in need[:limit]], settings=settings) if targets else {}
    for row in rows:
        url = canonical_url(row.get("url"))
        if row.get("is_full_text"):
            _apply_recovered_date(row, str(row.get("raw_text") or row.get("clean_text") or ""))
            continue
        if url not in targets:
            continue
        text = extracted.get(url)
        html = ""
        if not text:
            try:
                fetched = fetch_html(str(row.get("url") or ""), timeout=18)
                html = str(fetched.get("html") or "")
                text = _clean(fetched.get("text") or document_text(html))
            except Exception:
                text = ""
        if len(text) >= 400:
            row["clean_text"] = text
            row["raw_text"] = text
            row["is_full_text"] = True
        _apply_recovered_date(row, html or text)
    return rows


def recover_dates_from_pages(rows: list[dict[str, Any]], *, limit: int = 10) -> int:
    """Fetch HTML only to recover high-confidence dates for full-text undated docs."""
    recovered = 0
    candidates = [
        row
        for row in rows
        if not row.get("published_at") and row.get("is_full_text") and row.get("url") and int(row.get("source_tier") or 9) <= 4
    ]
    for row in candidates[:limit]:
        found = None
        html = ""
        try:
            fetched = fetch_html(str(row.get("url") or ""), timeout=12)
            html = str(fetched.get("html") or "")
            from .dates import recover_published_at

            found = recover_published_at(html)
        except Exception:
            found = None
        if found:
            row["published_at"] = found
            row["is_dated"] = True
            meta = dict(row.get("metadata") or {})
            meta["date_recovered"] = True
            row["metadata"] = meta
            recovered += 1
    return recovered
