"""Fetch official filings, exhibits, and keyless web search results.

Providers are tools. This module looks for reliable public documents when a
structured API is missing. No issuer-specific branches.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from stock_pm.events.bodies import extract_official_body_text, is_allowed_sec_host
from stock_pm.events.feeds import fetch_feed, strip_markup
from stock_pm.fetch import FetchError, json_get, text_get


BODY_LIMIT = 80_000
EXCERPT_LIMIT = 1_200
BROWSER_UA = "Mozilla/5.0 (compatible; StockPM-research/1.0; +https://github.com/)"
EXHIBIT_HREF_RE = re.compile(
    r"""href=["']([^"']*(?:ex[-_]?99|exhibit[-_]?99|ex99)[^"']*)["']""",
    re.I,
)
HREF_RE = re.compile(r"""href=["']([^"']+)["']""", re.I)
RESULT_A_RE = re.compile(
    r"""<a[^>]*class=["'][^"']*result__a[^"']*["'][^>]*href=["']([^"']+)["'][^>]*>(.*?)</a>""",
    re.I | re.S,
)
SNIPPET_RE = re.compile(
    r"""<a[^>]*class=["'][^"']*result__snippet[^"']*["'][^>]*>(.*?)</a>""",
    re.I | re.S,
)
TRANSCRIPT_HINTS = (
    "earnings call",
    "prepared remarks",
    "question-and-answer",
    "question and answer",
    "operator:",
    "transcript",
)
RELEASE_HINTS = (
    "expects",
    "outlook",
    "guidance",
    "revenue",
    "press release",
    "exhibit 99",
)


def _decode(raw: bytes) -> str:
    if not raw:
        return ""
    for encoding in ("utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def fetch_html(url: str, *, user_agent: str | None = None, timeout: float = 30) -> dict[str, Any]:
    target = str(url or "").strip()
    if not target.startswith("https://"):
        return {"url": target, "html": "", "text": "", "error": "unsupported_url"}
    ua = (user_agent or "").strip() or BROWSER_UA
    response = fetch_feed(
        target,
        user_agent=ua,
        extra_headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
        timeout=timeout,
        retries=1,
    )
    if not response.ok:
        return {"url": target, "html": "", "text": "", "error": response.error or f"http_{response.status_code}"}
    html = _decode(response.body)
    text = document_text(html)
    return {"url": str(response.url or target), "html": html, "text": text[:BODY_LIMIT], "error": None}


def document_text(html: str) -> str:
    body = extract_official_body_text(html) or strip_markup(html, max_len=None)
    return re.sub(r"[ \t]+", " ", str(body or "")).strip()


def accession_dashed(nodash: str) -> str:
    digits = re.sub(r"\D", "", str(nodash or ""))
    if len(digits) >= 18:
        return f"{digits[:10]}-{digits[10:12]}-{digits[12:18]}"
    return str(nodash or "")


def sec_index_url(filing_url: str) -> str | None:
    parsed = urlparse(str(filing_url or ""))
    parts = [item for item in parsed.path.split("/") if item]
    if "Archives" not in parts or "edgar" not in parts or "data" not in parts:
        return None
    if len(parts) < 5:
        return None
    accession = parts[-2]
    dashed = accession_dashed(accession)
    if not dashed or "-" not in dashed:
        return None
    base = str(filing_url).rsplit("/", 1)[0]
    return f"{base}/{dashed}-index.htm"


def exhibit_urls(html: str, base_url: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for href in EXHIBIT_HREF_RE.findall(html or ""):
        target = urljoin(base_url, href.strip())
        if target in seen or not target.startswith("https://"):
            continue
        if base_url.startswith("https://www.sec.gov") and not is_allowed_sec_host(target):
            continue
        seen.add(target)
        found.append(target)
    if found:
        return found[:4]
    for href in HREF_RE.findall(html or ""):
        low = href.lower()
        if not any(token in low for token in ("ex99", "ex-99", "ex_99", "exhibit99", "exhibit-99")):
            continue
        target = urljoin(base_url, href.strip())
        if target in seen or not target.startswith("https://"):
            continue
        seen.add(target)
        found.append(target)
        if len(found) >= 4:
            break
    return found


def unwrap_ddg(href: str) -> str:
    raw = str(href or "").strip()
    if not raw:
        return ""
    if "uddg=" in raw:
        query = parse_qs(urlparse(raw).query)
        values = query.get("uddg") or []
        if values:
            raw = unquote(values[0])
    if raw.startswith("//"):
        raw = "https:" + raw
    return raw


def web_search(query: str, *, user_agent: str | None = None, limit: int = 8) -> list[dict[str, str]]:
    q = str(query or "").strip()
    if not q:
        return []
    from urllib.parse import quote_plus

    ua = (user_agent or "").strip() or BROWSER_UA
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(q)}"
    response = fetch_feed(
        url,
        user_agent=ua,
        extra_headers={"Accept": "text/html"},
        timeout=25,
        retries=1,
    )
    if not response.ok:
        return []
    html = _decode(response.body)
    out: list[dict[str, str]] = []
    snippets = [strip_markup(item, max_len=280) for item in SNIPPET_RE.findall(html)]
    for idx, match in enumerate(RESULT_A_RE.finditer(html)):
        href = unwrap_ddg(match.group(1))
        title = strip_markup(match.group(2), max_len=180)
        if not href.startswith("https://") or not title:
            continue
        snippet = snippets[idx] if idx < len(snippets) else ""
        out.append({"title": title, "url": href, "snippet": snippet})
        if len(out) >= limit:
            break
    return out


def looks_like_transcript(text: str) -> bool:
    hay = (text or "").lower()
    if len(hay) < 1200:
        return False
    return any(token in hay for token in TRANSCRIPT_HINTS)


def looks_like_earnings_release(text: str) -> bool:
    hay = (text or "").lower()
    if len(hay) < 400:
        return False
    return any(token in hay for token in RELEASE_HINTS)


def ingest_official_filings(
    filings: list[dict[str, Any]],
    *,
    user_agent: str | None,
    max_filings: int = 8,
) -> list[dict[str, Any]]:
    """Fetch ~1 year of 10-Q / 10-K bodies plus recent 8-K Exhibit 99.1 when present."""
    docs: list[dict[str, Any]] = []
    ua = (user_agent or "").strip() or None

    def _form_rank(form: str) -> int:
        if form in {"10-K", "20-F"}:
            return 0
        if form in {"10-Q"}:
            return 1
        if form in {"8-K", "6-K"}:
            return 2
        return 3

    ordered = sorted(
        [row for row in filings if isinstance(row, dict)],
        key=lambda row: (
            _form_rank(str(row.get("form") or row.get("title") or "").upper()),
            0 if str(row.get("filing_date") or row.get("published_at") or "") else 1,
            str(row.get("filing_date") or row.get("published_at") or ""),
        ),
        reverse=True,
    )
    ordered.sort(key=lambda row: _form_rank(str(row.get("form") or row.get("title") or "").upper()))
    count = 0
    for row in ordered:
        form = str(row.get("form") or row.get("title") or "").upper()
        url = str(row.get("url") or "").strip()
        if not url or form not in {"8-K", "10-Q", "10-K", "20-F", "6-K"}:
            continue
        if count >= max_filings:
            break
        count += 1
        primary = fetch_html(url, user_agent=ua)
        text = str(primary.get("text") or "")
        html = str(primary.get("html") or "")
        docs.append(
            {
                "form": form,
                "title": form,
                "url": url,
                "published_at": row.get("filing_date") or row.get("published_at"),
                "text": text,
                "html": html,
                "doc_type": "filing",
                "source_provider": row.get("source_provider") or "sec",
                "error": primary.get("error"),
            }
        )
        exhibit_targets = exhibit_urls(html, url)
        index = sec_index_url(url)
        if index and not exhibit_targets:
            index_doc = fetch_html(index, user_agent=ua)
            exhibit_targets = exhibit_urls(str(index_doc.get("html") or ""), index)
        if form == "8-K" and not exhibit_targets and looks_like_earnings_release(text):
            continue
        for exhibit_url in exhibit_targets[:2]:
            exhibit = fetch_html(exhibit_url, user_agent=ua)
            exhibit_text = str(exhibit.get("text") or "")
            if len(exhibit_text) < 200:
                continue
            docs.append(
                {
                    "form": "EX-99.1",
                    "title": "Exhibit 99.1",
                    "url": exhibit_url,
                    "published_at": row.get("filing_date") or row.get("published_at"),
                    "text": exhibit_text,
                    "html": str(exhibit.get("html") or ""),
                    "doc_type": "earnings_release" if looks_like_earnings_release(exhibit_text) else "exhibit",
                    "source_provider": "sec.exhibit",
                    "error": exhibit.get("error"),
                    "parent_url": url,
                }
            )
    return docs


def search_official_materials(symbol: str, *, legal_name: str | None = None, user_agent: str | None = None) -> list[dict[str, Any]]:
    """Keyless web search for earnings releases and transcripts. Results are candidates, not evidence."""
    ticker = str(symbol or "").upper()
    name = str(legal_name or "").strip()
    queries = [
        f"{ticker} earnings release exhibit 99.1",
        f"{ticker} {name} earnings call transcript".strip(),
        f"{ticker} investor relations earnings",
    ]
    seen: set[str] = set()
    hits: list[dict[str, Any]] = []
    for query in queries:
        for row in web_search(query, user_agent=user_agent, limit=5):
            url = str(row.get("url") or "")
            if not url or url in seen:
                continue
            seen.add(url)
            hits.append({**row, "query": query})
            if len(hits) >= 12:
                return hits
    return hits


def fetch_search_candidates(candidates: list[dict[str, Any]], *, user_agent: str | None = None, limit: int = 4) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for row in candidates[:8]:
        if len(docs) >= limit:
            break
        url = str(row.get("url") or "")
        fetched = fetch_html(url, user_agent=user_agent)
        text = str(fetched.get("text") or "")
        if fetched.get("error") or len(text) < 400:
            continue
        kind = "transcript" if looks_like_transcript(text) else None
        if kind is None and looks_like_earnings_release(text):
            kind = "earnings_release"
        if kind is None:
            continue
        docs.append(
            {
                "title": row.get("title") or kind,
                "url": url,
                "published_at": None,
                "text": text,
                "doc_type": kind,
                "source_provider": "web_search",
                "query": row.get("query"),
            }
        )
    return docs


def parse_yahoo_chart(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = ((payload or {}).get("chart") or {}).get("result") or []
    if not result or not isinstance(result[0], dict):
        return []
    row = result[0]
    stamps = list(row.get("timestamp") or [])
    quote = ((row.get("indicators") or {}).get("quote") or [{}])[0]
    closes = list(quote.get("close") or [])
    opens = list(quote.get("open") or [])
    highs = list(quote.get("high") or [])
    lows = list(quote.get("low") or [])
    volumes = list(quote.get("volume") or [])
    from datetime import datetime, timezone

    bars: list[dict[str, Any]] = []
    for idx, stamp in enumerate(stamps):
        try:
            close = float(closes[idx]) if idx < len(closes) and closes[idx] is not None else None
        except (TypeError, ValueError, IndexError):
            close = None
        if close is None:
            continue
        try:
            when = datetime.fromtimestamp(int(stamp), tz=timezone.utc).replace(microsecond=0)
        except (TypeError, ValueError, OSError):
            continue
        def _num(series: list[Any]) -> float | None:
            if idx >= len(series) or series[idx] is None:
                return None
            try:
                return float(series[idx])
            except (TypeError, ValueError):
                return None

        bars.append(
            {
                "bar_time": when.isoformat(),
                "session_date": when.date().isoformat(),
                "open_price": _num(opens),
                "high_price": _num(highs),
                "low_price": _num(lows),
                "close_price": close,
                "volume": _num(volumes),
            }
        )
    bars.reverse()
    return bars


def parse_stooq_csv(text: str) -> list[dict[str, Any]]:
    from datetime import datetime, timezone

    bars: list[dict[str, Any]] = []
    for line in str(text or "").splitlines()[1:]:
        parts = [item.strip() for item in line.split(",")]
        if len(parts) < 5:
            continue
        try:
            day = datetime.strptime(parts[0], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            close = float(parts[4])
        except (TypeError, ValueError):
            continue
        def _num(raw: str) -> float | None:
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None

        bars.append(
            {
                "bar_time": day.isoformat(),
                "session_date": day.date().isoformat(),
                "open_price": _num(parts[1]) if len(parts) > 1 else None,
                "high_price": _num(parts[2]) if len(parts) > 2 else None,
                "low_price": _num(parts[3]) if len(parts) > 3 else None,
                "close_price": close,
                "volume": _num(parts[5]) if len(parts) > 5 else None,
            }
        )
    bars.reverse()
    return bars


def yahoo_daily_bars(symbol: str, *, range_value: str = "2y") -> dict[str, Any]:
    ticker = str(symbol or "").upper()
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range={range_value}&includeAdjustedClose=true"
    try:
        result = json_get(
            url,
            headers={"User-Agent": BROWSER_UA, "Accept": "application/json"},
            timeout=30,
            retries=2,
            cache_key=f"yahoo-chart-{ticker}-{range_value}",
        )
    except FetchError as exc:
        return {"bars": [], "source": None, "error": exc.reason_code}
    bars = parse_yahoo_chart(result.payload if isinstance(result.payload, dict) else {})
    if not bars:
        return {"bars": [], "source": None, "error": "upstream_empty"}
    return {"bars": bars, "source": "yahoo", "error": None}


def stooq_daily_bars(symbol: str) -> dict[str, Any]:
    ticker = str(symbol or "").upper().replace(".", "-")
    url = f"https://stooq.com/q/d/l/?s={ticker.lower()}.us&i=d"
    try:
        result = text_get(
            url,
            headers={"User-Agent": BROWSER_UA, "Accept": "text/csv"},
            timeout=30,
            retries=2,
            cache_key=f"stooq-{ticker}",
        )
    except FetchError as exc:
        return {"bars": [], "source": None, "error": exc.reason_code}
    bars = parse_stooq_csv(str(result.payload or ""))
    if not bars:
        return {"bars": [], "source": None, "error": "upstream_empty"}
    return {"bars": bars[:900], "source": "stooq", "error": None}
