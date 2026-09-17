"""Last-30-day news / filing search. Reuses official.web_search, pack news, and SEC."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from stock_pm.events.policy import TIER1_HOSTS, TIER2_HOSTS
from stock_pm.research.ids import new_id
from stock_pm.research.official import web_search

from .types import HIGH_QUALITY_NEWS_HOSTS, NEWS_WINDOW_DAYS


_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_ISO_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_TEXT_DATE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"[.\s\-]+(\d{1,2})(?:st|nd|rd|th)?[,.\s\-]+(20\d{2})\b",
    re.I,
)
_EU_DATE = re.compile(
    r"\b(\d{1,2})\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"[,\s]+(20\d{2})\b",
    re.I,
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _host(url: str | None) -> str:
    host = (urlparse(str(url or "")).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def source_family(url: str | None, source: str | None = None) -> str:
    host = _host(url)
    blob = f"{host} {source or ''}".lower()
    if "sec.gov" in blob:
        return "sec"
    if any(item in host for item in TIER2_HOSTS) or any(item in host for item in ("reuters.com", "bloomberg.com", "ft.com", "wsj.com")):
        return "high_quality_news"
    if any(item in host for item in TIER1_HOSTS):
        return "official"
    if "ir." in host or "investor" in host:
        return "issuer_ir"
    return "web_search"


def is_high_quality(url: str | None, source: str | None = None) -> bool:
    host = _host(url)
    return any(host.endswith(item) for item in HIGH_QUALITY_NEWS_HOSTS) or source_family(url, source) in {"sec", "official", "high_quality_news"}


def _extract_published_at(*parts: Any) -> str | None:
    for value in parts:
        if not value:
            continue
        text = str(value)
        try:
            stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return stamp.date().isoformat()
        except ValueError:
            pass
        match = _ISO_DATE.search(text)
        if match:
            return match.group(1)
        match = _TEXT_DATE.search(text)
        if match:
            month = _MONTHS.get(match.group(1).lower().rstrip("."))
            if month:
                return f"{match.group(3)}-{month:02d}-{int(match.group(2)):02d}"
        match = _EU_DATE.search(text)
        if match:
            month = _MONTHS.get(match.group(2).lower().rstrip("."))
            if month:
                return f"{match.group(3)}-{month:02d}-{int(match.group(1)):02d}"
    return None


def default_queries(ticker: str, name: str | None = None, *, days: int = NEWS_WINDOW_DAYS) -> list[str]:
    symbol = ticker.upper()
    legal = (name or symbol).strip()
    after = (_now() - timedelta(days=days)).date().isoformat()
    return [
        f'{symbol} OR "{legal}" news after:{after}',
        f'site:reuters.com "{legal}" after:{after}',
        f'site:bloomberg.com "{legal}" after:{after}',
        f'"{legal}" investor relations press release after:{after}',
        f'{symbol} customer OR supplier OR demand after:{after}',
        f'site:sec.gov {symbol} 10-Q OR 10-K OR 8-K after:{after}',
    ]


def _within_days(value: Any, days: int) -> bool:
    if not value:
        return False
    text = str(value)
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            stamp = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp >= _now() - timedelta(days=days)


def _from_pack(pack: dict[str, Any], *, days: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in pack.get("major_events") or []:
        if not isinstance(row, dict):
            continue
        published = _extract_published_at(
            row.get("published_at"),
            row.get("source_time"),
            row.get("event_time"),
            row.get("date"),
        )
        if not _within_days(published, days):
            continue
        out.append(
            {
                "title": row.get("headline") or row.get("title") or row.get("text") or "",
                "url": row.get("url") or row.get("source_url"),
                "snippet": row.get("summary") or row.get("excerpt") or row.get("text") or "",
                "source": row.get("source") or "news_articles",
                "published_at": published,
                "query": "pack.major_events",
            }
        )
    for row in pack.get("official_documents") or []:
        if not isinstance(row, dict):
            continue
        published = _extract_published_at(
            row.get("published_at"),
            row.get("source_time"),
            (row.get("metadata") or {}).get("filing_date"),
        )
        if not _within_days(published, days):
            continue
        out.append(
            {
                "title": row.get("title") or row.get("form") or "official",
                "url": row.get("url") or row.get("source_url"),
                "snippet": row.get("excerpt") or row.get("body") or "",
                "source": row.get("source_provider") or source_family(row.get("url")),
                "published_at": published,
                "query": "pack.official_documents",
            }
        )
    return out


def search_recent_news(
    ticker: str,
    *,
    pack: dict[str, Any] | None = None,
    extra_queries: list[str] | None = None,
    fetchers: Any | None = None,
    days: int = NEWS_WINDOW_DAYS,
    limit_per_query: int = 5,
) -> list[dict[str, Any]]:
    symbol = ticker.upper()
    profile = (pack or {}).get("company_profile") or {}
    name = profile.get("legal_name") or symbol
    queries = default_queries(symbol, name, days=days)
    for item in extra_queries or []:
        text = str(item or "").strip()
        if text and text not in queries:
            queries.append(text)
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _from_pack(pack or {}, days=days):
        key = str(row.get("url") or row.get("title") or "")
        if key and key not in seen:
            seen.add(key)
            hits.append(row)
    searcher = web_search
    if fetchers is not None and hasattr(fetchers, "web_search"):
        searcher = fetchers.web_search
    for query in queries[:14]:
        try:
            rows = searcher(query, limit=limit_per_query) if searcher is web_search else searcher(query)
        except TypeError:
            rows = searcher(query)
        except Exception:
            rows = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "")
            title = str(row.get("title") or "")
            key = url or title
            if not key or key in seen:
                continue
            published = _extract_published_at(
                row.get("published_at"),
                row.get("date"),
                title,
                row.get("snippet") or row.get("summary"),
            )
            if not _within_days(published, days):
                continue
            seen.add(key)
            hits.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": row.get("snippet") or row.get("summary") or "",
                    "source": source_family(url),
                    "published_at": published,
                    "query": query,
                }
            )
    return hits


def classify_news_hits(hits: list[dict[str, Any]], *, days: int = NEWS_WINDOW_DAYS) -> dict[str, Any]:
    official = 0
    independent = 0
    aggregator = 0
    headline_only = 0
    dated = 0
    undated = 0
    full_text = 0
    in_window = 0
    for row in hits:
        family = source_family(row.get("url"), row.get("source"))
        published = row.get("published_at")
        body = str(row.get("snippet") or row.get("new_fact") or row.get("excerpt") or "").strip()
        title = str(row.get("title") or "").strip()
        if published:
            dated += 1
        else:
            undated += 1
        if _within_days(published, days):
            in_window += 1
        if family in {"sec", "official", "issuer_ir"}:
            official += 1
        elif family == "high_quality_news":
            independent += 1
        else:
            aggregator += 1
        if len(body) >= 80 and title not in {"8-K", "10-Q", "10-K", "6-K", "20-F"}:
            full_text += 1
        elif len(body) < 40 or title in {"8-K", "10-Q", "10-K"}:
            headline_only += 1
    return {
        "official_sec": official,
        "high_quality_independent": independent,
        "aggregator": aggregator,
        "headline_only": headline_only,
        "dated": dated,
        "undated": undated,
        "full_text_available": full_text,
        "in_window": in_window,
        "count": len(hits),
        "window_days": days,
    }


def hits_to_evidence_bodies(ticker: str, hits: list[dict[str, Any]], *, retrieved_at: str) -> list[dict[str, Any]]:
    """Search snippets are not Evidence. Only dated full-text / extracted facts qualify."""
    bodies: list[dict[str, Any]] = []
    for row in hits:
        if not row.get("is_full_text") and not row.get("extracted_fact"):
            continue
        if not row.get("published_at"):
            continue
        title = str(row.get("title") or "").strip()
        snippet = str(row.get("snippet") or row.get("excerpt") or row.get("extracted_fact") or "").strip()
        fact = str(row.get("extracted_fact") or snippet or title).strip()
        if not fact:
            continue
        published = row.get("published_at")
        url = row.get("url")
        if not url:
            continue
        bodies.append(
            {
                "id": new_id("rev"),
                "ticker": ticker.upper(),
                "evidence_type": "news",
                "fact": fact[:800],
                "excerpt": (snippet or title)[:600],
                "source": row.get("source") or source_family(url),
                "source_url": url,
                "source_time": published,
                "retrieved_at": retrieved_at,
                "source_type": "web_search" if source_family(url) == "web_search" else source_family(url),
                "importance": "high" if is_high_quality(url, row.get("source")) else "medium",
                "raw_reference": {
                    "query": row.get("query"),
                    "title": title,
                    "source_family": source_family(url, row.get("source")),
                },
            }
        )
    return bodies
