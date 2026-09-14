"""CSE discovery → safe official fetch → Tier-1 promotion.

Google CSE (and other search snippets) stay discovery-only until a fetched
official original supports the candidate's material claim actions/fields.
Entity overlap alone never promotes a snippet claim. Promoted documents
use official title/claim/date. Failed or unverified candidates keep a
local reason and next retry; they never enter directional evidence.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

from .bodies import extract_official_body_text, fetch_official_page, official_html_excerpt, resolve_redirect_url
from .evidence import STOP
from .feeds import RateLimiter, strip_markup
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
ENTITY_ALIASES = frozenset({
    "nvda", "nvidia", "aapl", "apple", "xom", "exxon", "exxonmobil",
    "jpm", "jpmorgan", "nok", "nokia", "ofac", "iran",
    "corporation", "company", "inc", "corp", "llc", "ltd",
    "英伟达", "苹果", "埃克森", "摩根", "诺基亚",
})
HIGH_SIGNAL_ACTIONS = frozenset({
    "bankruptcy", "bankrupt", "insolvency", "defaulted", "default",
    "chapter", "8-k", "8k", "10-k", "10k", "10-q", "10q", "13f",
    "filed", "filing", "filings",
    "guidance", "dividend", "buyback",
    "acquisition", "acquire", "acquired", "merger", "takeover",
    "layoff", "layoffs", "recall", "investigation", "subpoena",
    "sanction", "sanctions", "tariff", "tariffs", "embargo",
    "hike", "cut", "pause",
    "earnings", "outlook",
    "designated", "designation",
    "破产", "并购", "收购", "分红", "回购", "裁员", "制裁", "关税", "立案",
})
FORM_RE = re.compile(r"\b(?:form\s+)?(8-k|10-k|10-q|13f|\d-k|\d-q)\b", re.I)
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]{2,}|[\u4e00-\u9fff]{2,}")
NEGATION_RE = re.compile(
    r"\b(not|no|never|without|isn't|aren't|wasn't|weren't|didn't|doesn't|don't|cannot|can't)\b|"
    r"未|并无|并非|否认|不存在|没有",
    re.I,
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


def _entity_stop(doc: EventDocument) -> set[str]:
    stop = set(ENTITY_ALIASES)
    for item in doc.entities or []:
        token = str(item or "").strip().lower()
        if token:
            stop.add(token)
            stop.update(part for part in token.replace("-", " ").split() if part)
    return stop


def _normalize_action_token(token: str) -> str:
    raw = (token or "").lower().replace(" ", "")
    if raw in {"8k", "form8-k", "form8k"}:
        return "8-k"
    if raw in {"10k", "form10-k", "form10k"}:
        return "10-k"
    if raw in {"10q", "form10-q", "form10q"}:
        return "10-q"
    return raw


def distinctive_claim_actions(text: str, entity_stop: set[str] | None = None) -> list[str]:
    """Material claim actions/fields. Entities and stopwords never count."""
    raw = (text or "").lower()
    blocked = set(entity_stop or ()) | set(STOP)
    found: list[str] = []

    def _add(token: str) -> None:
        key = _normalize_action_token(token)
        if key and key not in found and key not in blocked:
            found.append(key)

    for match in FORM_RE.finditer(raw):
        _add(match.group(1))
    for word in TOKEN_RE.findall(raw):
        if word in blocked:
            continue
        key = _normalize_action_token(word)
        if key in HIGH_SIGNAL_ACTIONS or key.endswith("-k") or key.endswith("-q"):
            _add(key)
    return found


def _first_match_index(hay: str, token: str) -> int:
    variants = {token}
    if token == "8-k":
        variants.update({"8-k", "8k", "form 8-k"})
    if token == "10-k":
        variants.update({"10-k", "10k", "form 10-k"})
    if token == "10-q":
        variants.update({"10-q", "10q", "form 10-q"})
    best = -1
    for item in variants:
        idx = hay.find(item)
        if idx >= 0 and (best < 0 or idx < best):
            best = idx
    return best


def _window_negated(hay: str, start: int, token: str) -> bool:
    window = hay[max(0, start - 48): start + max(len(token), 4) + 24]
    return bool(NEGATION_RE.search(window))


def official_body_supports_claim_actions(
    body: str,
    candidate_text: str,
    entity_stop: set[str] | None = None,
) -> tuple[bool, str]:
    """True only when official body supports every distinctive claim action."""
    tokens = distinctive_claim_actions(candidate_text, entity_stop)
    if not tokens:
        return False, "no_distinctive_action_tokens"
    hay = (body or "").lower()
    if not hay.strip():
        return False, "empty_official_body"
    problems: list[str] = []
    for token in tokens:
        idx = _first_match_index(hay, token)
        if idx < 0:
            problems.append(f"missing_action:{token}")
            continue
        if _window_negated(hay, idx, token):
            problems.append(f"negated_action:{token}")
    if problems:
        return False, ",".join(problems)
    return True, "ok"


def extract_official_title(html: str) -> str:
    for pattern in (
        r"(?is)<title[^>]*>(.*?)</title>",
        r'''(?is)<meta[^>]+property=["']og:title["'][^>]+content=["']([^"']+)''',
        r"(?is)<h1[^>]*>(.*?)</h1>",
    ):
        match = re.search(pattern, html or "")
        if not match:
            continue
        title = strip_markup(match.group(1), max_len=240).strip()
        if title:
            return title
    return ""


def extract_official_claim(body: str, title: str = "") -> str:
    text = (body or "").strip()
    if not text:
        return (title or "").strip()
    sentence = re.split(r"(?<=[.!?。])\s+", text, maxsplit=1)[0].strip()
    if 12 <= len(sentence) <= 400:
        return sentence
    return (title or text[:240]).strip()


def extract_official_published_at(html: str, page: dict[str, Any] | None, fallback: str) -> str:
    for pattern in (
        r'''(?is)<meta[^>]+property=["']article:published_time["'][^>]+content=["']([^"']+)''',
        r'''(?is)<time[^>]+datetime=["']([^"']+)''',
    ):
        match = re.search(pattern, html or "")
        if match:
            return str(match.group(1) or "").strip()[:40]
    row = page or {}
    return str(row.get("last_modified") or row.get("fetched_at") or fallback)[:40]


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
    official_title: str,
    official_claim: str,
    official_published_at: str,
    fetched_at: str | None,
    now: datetime,
) -> EventDocument:
    title = official_title or official_claim
    claim = official_claim or official_title
    return EventDocument(
        title=title,
        url=url,
        publisher=_publisher_for_url(url),
        published_at=official_published_at or fetched_at or _iso(now),
        event_type=doc.event_type,
        entities=list(doc.entities or []),
        countries=list(doc.countries or []),
        claims=[claim] if claim else [],
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
        official_body = extract_official_body_text(html)
        if not official_body.strip():
            out.append(_mark_unverified(doc, reason="empty_official_body", now=clock))
            unverified.append({"url": url, "reason": "empty_official_body", "next_retry_at": str(doc.next_retry_at or "")})
            continue
        candidate_text = _claim_for(doc)
        supported, why = official_body_supports_claim_actions(
            official_body,
            candidate_text,
            _entity_stop(doc),
        )
        if not supported:
            reason = f"official_body_did_not_validate:{why}"
            out.append(_mark_unverified(doc, reason=reason, now=clock))
            unverified.append({"url": url, "reason": reason, "next_retry_at": str(doc.next_retry_at or "")})
            continue
        official_title = extract_official_title(html)
        official_claim = extract_official_claim(official_body, official_title)
        if not official_claim:
            out.append(_mark_unverified(doc, reason="official_claim_unavailable", now=clock))
            unverified.append({"url": url, "reason": "official_claim_unavailable", "next_retry_at": str(doc.next_retry_at or "")})
            continue
        excerpt = official_html_excerpt(html, official_claim)
        if not excerpt:
            excerpt = sanitize_untrusted(official_body, max_len=480)
        if not excerpt:
            out.append(_mark_unverified(doc, reason="official_excerpt_unavailable", now=clock))
            unverified.append({"url": url, "reason": "official_excerpt_unavailable", "next_retry_at": str(doc.next_retry_at or "")})
            continue
        official = _promote_official(
            doc,
            url=final_url if is_tier1_https(final_url) else url,
            excerpt=excerpt,
            official_title=official_title or official_claim,
            official_claim=official_claim,
            official_published_at=extract_official_published_at(html, page, _iso(clock)),
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
