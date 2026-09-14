"""CSE discovery → safe official fetch → Tier-1 promotion.

Google CSE (and other search snippets) stay discovery-only until a fetched
official original is validated. Failed or unverified candidates keep a local
reason and next retry; they never enter directional evidence.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

from .bodies import fetch_official_page, official_html_excerpt, resolve_redirect_url
from .evidence import excerpt_supports_claim
from .feeds import RateLimiter
from .live import DEFAULT_SEC_UA
from .policy import (
    host_of,
    http_redirect_allowed,
    is_discovery_snippet,
    is_safe_public_http_url,
    is_tier1_https,
    sanitize_untrusted,
)
from .types import EventDocument


RETRY_AFTER = timedelta(hours=6)
_LIMITER = RateLimiter(0.25)
_HOST_PUBLISHER = (
    ("sec.gov", "U.S. Securities and Exchange Commission"),
    ("treasury.gov", "U.S. Department of the Treasury"),
    ("federalreserve.gov", "Board of Governors of the Federal Reserve System"),
    ("eia.gov", "U.S. Energy Information Administration"),
    ("bls.gov", "U.S. Bureau of Labor Statistics"),
    ("bea.gov", "U.S. Bureau of Economic Analysis"),
    ("stlouisfed.org", "Federal Reserve Bank of St. Louis"),
    ("whitehouse.gov", "The White House"),
    ("congress.gov", "U.S. Congress"),
    ("ecb.europa.eu", "European Central Bank"),
    ("imf.org", "International Monetary Fund"),
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(stamp: datetime) -> str:
    return stamp.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _publisher_for_url(url: str) -> str:
    host = host_of(url)
    for root, name in _HOST_PUBLISHER:
        if host == root or host.endswith("." + root):
            return name
    return host or "official"


def _due(doc: EventDocument, now: datetime) -> bool:
    raw = getattr(doc, "next_retry_at", None)
    if not raw:
        return True
    try:
        nxt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return True
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=timezone.utc)
    return nxt <= now


def _claim_for(doc: EventDocument) -> str:
    if doc.claims:
        return str(doc.claims[0] or doc.title or "")
    return str(doc.title or "")


def _tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9\u4e00-\u9fff]{3,}", (text or "").lower())}


def _body_supports_candidate(doc: EventDocument, excerpt: str) -> bool:
    hay = excerpt.lower()
    entities = [str(item) for item in (doc.entities or []) if str(item).strip()]
    if entities:
        hits = sum(1 for item in entities if item.lower() in hay)
        if hits >= min(2, len(entities)) or (len(entities) == 1 and hits == 1):
            return True
    claim = _claim_for(doc)
    if excerpt_supports_claim(claim, excerpt, required=None):
        return True
    title_tokens = _tokens(doc.title)
    if title_tokens and len(title_tokens & _tokens(excerpt)) >= min(2, len(title_tokens)):
        return True
    return False


def _mark_unverified(doc: EventDocument, *, reason: str, now: datetime) -> EventDocument:
    doc.fetch_error = reason
    doc.discovery_role = doc.discovery_role or "discovery_candidate"
    doc.body_source = doc.body_source or "cse_snippet"
    doc.next_retry_at = _iso(now + RETRY_AFTER)
    return doc


def _promote_official(
    doc: EventDocument,
    *,
    url: str,
    excerpt: str,
    fetched_at: str | None,
    now: datetime,
) -> EventDocument:
    return EventDocument(
        title=doc.title,
        url=url,
        publisher=_publisher_for_url(url),
        published_at=doc.published_at or fetched_at or _iso(now),
        event_type=doc.event_type,
        entities=list(doc.entities or []),
        countries=list(doc.countries or []),
        claims=list(doc.claims or [doc.title]),
        body=sanitize_untrusted(excerpt),
        provider="official",
        status=doc.status or "active",
        etag=doc.etag,
        last_modified=doc.last_modified,
        document_role=None,
        evidence_role="event_fact",
        supersedes_url=doc.supersedes_url,
        last_fetched_at=fetched_at or _iso(now),
        body_source="official_html",
        fetch_error=None,
        filing_items=list(doc.filing_items or []),
        author=None,
        discovery_role=None,
        next_retry_at=None,
    )


def resolve_discovery_candidates(
    docs: list[EventDocument],
    *,
    now: datetime | None = None,
    fetch_page: Callable[..., dict[str, Any]] | None = None,
    user_agent: str | None = None,
) -> tuple[list[EventDocument], dict[str, Any]]:
    """Fetch allowlisted official URLs discovered by CSE. Snippets stay unverified."""
    clock = now or _now()
    do_fetch = fetch_page or fetch_official_page
    ua = user_agent or DEFAULT_SEC_UA
    out: list[EventDocument] = []
    promoted: list[str] = []
    unverified: list[dict[str, str]] = []
    skipped = 0
    seen_official: set[str] = set()
    for doc in docs:
        if not is_discovery_snippet(doc):
            out.append(doc)
            if doc.url:
                seen_official.add(doc.url)
            continue
        if not _due(doc, clock):
            skipped += 1
            out.append(doc)
            unverified.append({
                "url": doc.url,
                "reason": doc.fetch_error or "retry_deferred",
                "next_retry_at": str(doc.next_retry_at or ""),
            })
            continue
        url = str(doc.url or "").strip()
        if not url or not is_safe_public_http_url(url) or urlsplit(url).scheme != "https":
            out.append(_mark_unverified(doc, reason="unsafe_or_non_https_url", now=clock))
            unverified.append({"url": url, "reason": "unsafe_or_non_https_url", "next_retry_at": str(doc.next_retry_at or "")})
            continue
        if not is_tier1_https(url):
            out.append(_mark_unverified(doc, reason="not_allowlisted_official_host", now=clock))
            unverified.append({"url": url, "reason": "not_allowlisted_official_host", "next_retry_at": str(doc.next_retry_at or "")})
            continue
        page = do_fetch(url, user_agent=ua, limiter=_LIMITER if fetch_page is None else None)
        if not isinstance(page, dict):
            page = {}
        error = str(page.get("error") or "") or (None if page.get("status") == "ok" else str(page.get("status") or "fetch_failed"))
        html = str(page.get("html") or "")
        final_url = str(page.get("final_url") or page.get("url") or url)
        if error or not html:
            out.append(_mark_unverified(doc, reason=error or "empty_official_body", now=clock))
            unverified.append({"url": url, "reason": error or "empty_official_body", "next_retry_at": str(doc.next_retry_at or "")})
            continue
        if final_url and final_url != url:
            if not http_redirect_allowed(url, final_url) or not is_tier1_https(final_url):
                out.append(_mark_unverified(doc, reason="redirect_left_official_host", now=clock))
                unverified.append({"url": url, "reason": "redirect_left_official_host", "next_retry_at": str(doc.next_retry_at or "")})
                continue
            redirect = resolve_redirect_url(url, html)
            if redirect and redirect != url and is_tier1_https(redirect):
                final_url = redirect
        claim = _claim_for(doc)
        excerpt = official_html_excerpt(html, claim)
        if not excerpt:
            excerpt = sanitize_untrusted(re.sub(r"<[^>]+>", " ", html), max_len=480)
            if not excerpt or not _body_supports_candidate(doc, excerpt):
                out.append(_mark_unverified(doc, reason="official_body_did_not_validate", now=clock))
                unverified.append({"url": url, "reason": "official_body_did_not_validate", "next_retry_at": str(doc.next_retry_at or "")})
                continue
        elif not _body_supports_candidate(doc, excerpt):
            out.append(_mark_unverified(doc, reason="official_body_did_not_validate", now=clock))
            unverified.append({"url": url, "reason": "official_body_did_not_validate", "next_retry_at": str(doc.next_retry_at or "")})
            continue
        official = _promote_official(
            doc,
            url=final_url if is_tier1_https(final_url) else url,
            excerpt=excerpt,
            fetched_at=str(page.get("fetched_at") or "") or _iso(clock),
            now=clock,
        )
        # Snippet stays discovery-only; only the fetched original is Tier-1 evidence.
        out.append(doc)
        if official.url not in seen_official:
            out.append(official)
            seen_official.add(official.url)
            promoted.append(official.url)
    report = {
        "discovery_promoted": len(promoted),
        "discovery_unverified": len(unverified),
        "discovery_retry_deferred": skipped,
        "promoted_urls": promoted,
        "unverified": unverified,
        "schedule_entry": "stock-pm-events / run_event_job",
    }
    return out, report
