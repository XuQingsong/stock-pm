"""Map payloads that stock-pm already fetches onto RawArticle.

Adapters are pure: they take the vendor row exactly as the existing client
received it and never perform HTTP. Upstream fetching stays in
``fundamentals`` (Nasdaq), ``external.clients`` (Alpha Vantage / Tavily /
Exa) and ``events.live`` (SEC / Fed / EIA).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from stock_pm.events.live import WATCHLIST_CIKS
from stock_pm.events.types import EventDocument
from stock_pm.external.quality import canonical_url

from .contract import RawArticle
from .timeutil import normalize_published, utc_now

NASDAQ_BASE = "https://www.nasdaq.com"
ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")
CIK_RE = re.compile(r"^\d{10}$")
SEC_FORM_RE = re.compile(r"^\s*(8-K(?:/A)?|6-K(?:/A)?|10-K(?:/A)?|10-Q(?:/A)?)\b", re.I)
SEC_ITEM_RE = re.compile(r"Item\s+(\d+\.\d+)", re.I)
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")

# Alpha Vantage does not document the zone of time_published; common clients read it as UTC.
ALPHA_VANTAGE_NAIVE_TZ = "UTC"


def _tickers(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        ticker = str(value or "").strip().upper()
        if ticker and TICKER_RE.match(ticker) and ticker not in out:
            out.append(ticker)
    return out


def _fetched(value: datetime | None) -> datetime:
    return value or utc_now()


def from_nasdaq_row(row: dict[str, Any], *, symbol: str, fetched_at: datetime | None = None) -> RawArticle:
    """Nasdaq ``news/topic/articlebysymbol`` row. ``created`` is a date without time."""
    path = str(row.get("url") or "")
    url = path if path.startswith("http") else f"{NASDAQ_BASE}{path}"
    related = [str(item).split("|", 1)[0] for item in row.get("related_symbols") or []]
    tickers = _tickers([symbol, row.get("primarysymbol") or "", *related])
    vendor_id = row.get("id")
    return RawArticle(
        source="nasdaq_news",
        source_kind="aggregator",
        url=url,
        canonical_url=canonical_url(url),
        title=str(row.get("title") or ""),
        summary=str(row.get("description") or ""),
        publisher=(str(row.get("publisher") or "").strip() or None),
        published=normalize_published(row.get("created")),
        fetched_at=_fetched(fetched_at),
        external_id=str(vendor_id) if vendor_id not in (None, "") else None,
        external_id_kind="vendor_id" if vendor_id not in (None, "") else None,
        vendor_tickers=tickers,
        native={key: row.get(key) for key in ("ago", "primarytopic", "primarysymbol") if row.get(key) is not None},
    )


def from_alpha_vantage_item(item: dict[str, Any], *, fetched_at: datetime | None = None) -> RawArticle:
    """Alpha Vantage ``NEWS_SENTIMENT`` feed item, kept with its ticker/topic metadata."""
    url = str(item.get("url") or "")
    meta = []
    for row in item.get("ticker_sentiment") or []:
        if not isinstance(row, dict) or not row.get("ticker"):
            continue
        meta.append(
            {
                "ticker": str(row["ticker"]).upper(),
                "relevance_score": row.get("relevance_score"),
                "sentiment_score": row.get("ticker_sentiment_score"),
                "sentiment_label": row.get("ticker_sentiment_label"),
            }
        )
    topics = [str(row.get("topic")) for row in item.get("topics") or [] if isinstance(row, dict) and row.get("topic")]
    return RawArticle(
        source="alpha_vantage_news",
        source_kind="vendor_feed",
        url=url,
        canonical_url=canonical_url(url),
        title=str(item.get("title") or ""),
        summary=str(item.get("summary") or ""),
        publisher=(str(item.get("source") or "").strip() or None),
        authors=[str(name) for name in item.get("authors") or [] if name],
        published=normalize_published(item.get("time_published"), naive_tz=ALPHA_VANTAGE_NAIVE_TZ),
        fetched_at=_fetched(fetched_at),
        vendor_tickers=_tickers([row["ticker"] for row in meta]),
        vendor_ticker_meta=meta,
        vendor_topics=topics,
        native={
            key: item.get(key)
            for key in ("source_domain", "category_within_source", "overall_sentiment_score", "overall_sentiment_label")
            if item.get(key) is not None
        },
    )


def _sec_parts(doc: EventDocument) -> tuple[str | None, str | None, list[str]]:
    accession = next((item for item in doc.entities if ACCESSION_RE.match(item)), None)
    cik = next((item for item in doc.entities if CIK_RE.match(item)), None)
    tickers = [WATCHLIST_CIKS[cik]] if cik in WATCHLIST_CIKS else []
    return accession, cik, tickers


def from_sec_document(doc: EventDocument, *, fetched_at: datetime | None = None) -> RawArticle:
    """SEC EDGAR Atom entry after ``events.live`` enrichment (Items from the filing index)."""
    accession, cik, tickers = _sec_parts(doc)
    form_match = SEC_FORM_RE.match(doc.title or "")
    items = []
    for label in doc.filing_items:
        match = SEC_ITEM_RE.search(label)
        if match and match.group(1) not in items:
            items.append(match.group(1))
    return RawArticle(
        source="sec_edgar",
        source_kind="official",
        url=doc.url,
        canonical_url=canonical_url(doc.url),
        title=doc.title,
        summary=doc.body,
        publisher="SEC EDGAR",
        published=normalize_published(doc.published_at),
        fetched_at=_fetched(fetched_at or _parse_stamp(doc.last_fetched_at)),
        external_id=accession,
        external_id_kind="sec_accession" if accession else None,
        vendor_tickers=tickers,
        sec_form=form_match.group(1).upper() if form_match else None,
        sec_items=items,
        sec_accession=accession,
        sec_cik=cik,
        native={"filing_item_labels": list(doc.filing_items), "unmapped_filer": "UNMAPPED_FILER" in doc.entities},
    )


def from_official_document(doc: EventDocument, *, source: str, fetched_at: datetime | None = None) -> RawArticle:
    """Fed / EIA RSS item. These feeds expose no stable id beyond the URL."""
    return RawArticle(
        source=source,
        source_kind="official",
        url=doc.url,
        canonical_url=canonical_url(doc.url),
        title=doc.title,
        summary=doc.body,
        publisher=doc.publisher or None,
        published=normalize_published(doc.published_at),
        fetched_at=_fetched(fetched_at or _parse_stamp(doc.last_fetched_at)),
        external_id=canonical_url(doc.url) or None,
        external_id_kind="url",
        company_scoped=False,
        native={"event_type": doc.event_type, "entities": list(doc.entities)},
    )


def from_discovery_document(doc: dict[str, Any]) -> RawArticle:
    """Tavily / Exa / DuckDuckGo document from ``external.clients._document``.

    ``published_at`` there is already truncated to a date, so precision is day.
    """
    url = str(doc.get("url") or "")
    ticker = doc.get("ticker")
    vendor_id = (doc.get("metadata") or {}).get("exa_id")
    return RawArticle(
        source=str(doc.get("provider") or "discovery"),
        source_kind="discovery",
        url=url,
        canonical_url=str(doc.get("canonical_url") or canonical_url(url)),
        title=str(doc.get("title") or ""),
        summary=str(doc.get("clean_text") or "")[:600],
        body=str(doc.get("clean_text") or "") if doc.get("is_full_text") else "",
        publisher=(str(doc.get("source_domain") or "").strip() or None),
        authors=[str(doc["author"])] if doc.get("author") else [],
        published=normalize_published(doc.get("published_at")),
        fetched_at=_parse_stamp(doc.get("fetched_at")) or utc_now(),
        external_id=str(vendor_id) if vendor_id else None,
        external_id_kind="vendor_id" if vendor_id else None,
        vendor_tickers=_tickers([ticker]) if ticker else [],
        company_scoped=bool(ticker),
        native={"query": doc.get("query"), "query_type": doc.get("query_type"), "source_tier": doc.get("source_tier")},
    )


def _parse_stamp(value: Any) -> datetime | None:
    parsed = normalize_published(value, naive_tz="UTC") if value else None
    return parsed.utc if parsed and parsed.has_time_of_day else None
