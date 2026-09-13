"""Official HTML body helpers. RSS titles and navigation never count as excerpts."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

from .evidence import STOP, drop_chrome_lines, excerpt_supports_claim, normalize_evidence_text, select_claim_support_excerpt
from .feeds import FeedResponse, fetch_feed, strip_markup
from .policy import sanitize_untrusted

ITEM_RE = re.compile(r"Item\s+(\d+\.\d+)\s*:\s*([A-Za-z][^\n<]{8,200})", re.I)
NAV_NOISE = (
    "skip to",
    "an official website",
    "edgar filing documents",
    "complete submission text file",
    "form 8-k - current report",
    "page form 8-k",
    "sec accession no",
)
_CACHE: dict[str, dict[str, Any]] = {}


def reset_body_cache() -> None:
    _CACHE.clear()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _claim_tokens(claim: str) -> list[str]:
    words = re.findall(r"[a-z0-9\u4e00-\u9fff]{4,}", (claim or "").lower())
    return [word for word in words if word not in STOP]


def is_chrome_text(text: str) -> bool:
    hay = normalize_evidence_text(text).lower()
    if not hay:
        return True
    return any(marker in hay for marker in NAV_NOISE) and "item " not in hay


def extract_sec_index_items(html: str) -> list[str]:
    """Official EDGAR index Item lines only. Viewer/nav chrome is dropped."""
    raw = str(html or "")
    text = strip_markup(raw, max_len=None)
    rows: list[str] = []
    for match in ITEM_RE.finditer(raw + "\n" + text):
        line = normalize_evidence_text(f"Item {match.group(1)}: {match.group(2)}")
        line = sanitize_untrusted(line, max_len=240)
        if not line or is_chrome_text(line):
            continue
        if "item " not in line.lower() or ":" not in line:
            continue
        rows.append(line)
    return list(dict.fromkeys(rows))


def official_html_excerpt(html: str, claim: str) -> str | None:
    """Smallest official-body window that supports the claim. Title/nav cannot substitute."""
    cleaned = drop_chrome_lines(strip_markup(str(html or ""), max_len=None))
    cleaned = normalize_evidence_text(cleaned)
    if not cleaned or is_chrome_text(cleaned):
        return None
    if not excerpt_supports_claim(claim, cleaned):
        return None
    tokens = _claim_tokens(claim)
    if len(tokens) >= 2:
        try:
            window = select_claim_support_excerpt(cleaned, tokens[:3])
            excerpt = sanitize_untrusted(str(window.get("claim_support_excerpt") or ""), max_len=480)
            if excerpt and excerpt_supports_claim(claim, excerpt) and not is_chrome_text(excerpt):
                return excerpt
        except ValueError:
            pass
    lowered = cleaned.lower()
    needle = normalize_evidence_text(claim).lower()
    if needle and needle in lowered:
        start = lowered.find(needle)
        excerpt = sanitize_untrusted(cleaned[start : start + min(len(claim) + 80, 480)], max_len=480)
        if excerpt_supports_claim(claim, excerpt) and not is_chrome_text(excerpt):
            return excerpt
    return None


def fetch_official_page(
    url: str,
    *,
    user_agent: str,
    extra_headers: dict[str, str] | None = None,
    limiter=None,
    allow_cache: bool = True,
    fetch=None,
) -> dict[str, Any]:
    fetched_at = _now()
    cached = _CACHE.get(url) if allow_cache else None
    etag = (cached or {}).get("etag")
    last_modified = (cached or {}).get("last_modified")
    do_fetch = fetch or fetch_feed
    resp: FeedResponse = do_fetch(
        url,
        user_agent=user_agent,
        extra_headers=extra_headers,
        etag=etag,
        last_modified=last_modified,
        timeout=35,
        limiter=limiter,
        retries=2,
    )
    if resp.not_modified and cached:
        cached = dict(cached)
        cached["fetched_at"] = fetched_at
        cached["not_modified"] = True
        _CACHE[url] = cached
        return cached
    if resp.error or not resp.ok:
        return {
            "url": url,
            "html": "",
            "error": resp.error or f"http_{resp.status_code}",
            "http_status": resp.status_code,
            "fetched_at": fetched_at,
            "etag": resp.etag,
            "last_modified": resp.last_modified,
            "not_modified": False,
        }
    html = (resp.body or b"").decode("utf-8", "replace")
    row = {
        "url": resp.url or url,
        "html": html,
        "error": None,
        "http_status": resp.status_code,
        "fetched_at": fetched_at,
        "etag": resp.etag,
        "last_modified": resp.last_modified,
        "not_modified": False,
        "final_url": resp.url or url,
    }
    _CACHE[url] = {k: v for k, v in row.items() if k != "html"} | {"html": html}
    if resp.url and resp.url != url:
        _CACHE[resp.url] = _CACHE[url]
    return row


def resolve_redirect_url(base: str, html: str) -> str | None:
    match = re.search(r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\'][^"\']*url=([^"\']+)', html or "", flags=re.I)
    if not match:
        return None
    target = match.group(1).strip()
    if not target:
        return None
    return urljoin(base, target)
