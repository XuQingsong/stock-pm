"""Last-7-day news / filing search. Reuses official.web_search, pack news, and SEC."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from stock_pm.events.policy import TIER1_HOSTS, TIER2_HOSTS
from stock_pm.research.ids import new_id
from stock_pm.research.official import web_search

from .types import HIGH_QUALITY_NEWS_HOSTS


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


def default_queries(ticker: str, name: str | None = None) -> list[str]:
    symbol = ticker.upper()
    legal = (name or symbol).strip()
    after = (_now() - timedelta(days=7)).date().isoformat()
    return [
        f'{symbol} OR "{legal}" news after:{after}',
        f'{symbol} earnings OR guidance OR outlook OR 10-Q OR 8-K',
        f'site:sec.gov {symbol}',
        f'site:reuters.com "{legal}"',
        f'site:bloomberg.com "{legal}"',
        f'"{legal}" investor relations press release',
        f'{symbol} customer OR supplier OR demand',
    ]


def _within_days(value: Any, days: int) -> bool:
    if not value:
        return True
    text = str(value)
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return True
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp >= _now() - timedelta(days=days)


def _from_pack(pack: dict[str, Any], *, days: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in pack.get("major_events") or []:
        if not isinstance(row, dict):
            continue
        published = row.get("published_at") or row.get("source_time") or row.get("date")
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
    return out


def search_recent_news(
    ticker: str,
    *,
    pack: dict[str, Any] | None = None,
    extra_queries: list[str] | None = None,
    fetchers: Any | None = None,
    days: int = 7,
    limit_per_query: int = 5,
) -> list[dict[str, Any]]:
    symbol = ticker.upper()
    profile = (pack or {}).get("company_profile") or {}
    name = profile.get("legal_name") or symbol
    queries = default_queries(symbol, name)
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
            seen.add(key)
            hits.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": row.get("snippet") or row.get("summary") or "",
                    "source": source_family(url),
                    "published_at": row.get("published_at") or row.get("date"),
                    "query": query,
                }
            )
    return hits


def hits_to_evidence_bodies(ticker: str, hits: list[dict[str, Any]], *, retrieved_at: str) -> list[dict[str, Any]]:
    bodies: list[dict[str, Any]] = []
    for row in hits:
        title = str(row.get("title") or "").strip()
        snippet = str(row.get("snippet") or "").strip()
        fact = snippet or title
        if not fact:
            continue
        published = row.get("published_at") or retrieved_at
        url = row.get("url")
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
