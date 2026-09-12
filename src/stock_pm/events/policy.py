"""Source tiers, URL normalization, and untrusted-content hygiene."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .types import EventDocument


TIER1_HOSTS = (
    "treasury.gov",
    "sec.gov",
    "federalreserve.gov",
    "whitehouse.gov",
    "congress.gov",
    "eia.gov",
    "bls.gov",
    "bea.gov",
    "stlouisfed.org",
    "fred.stlouisfed.org",
    "ecb.europa.eu",
    "imf.org",
    "ofac.treasury.gov",
    "home.treasury.gov",
)
TIER2_HOSTS = (
    "reuters.com",
    "apnews.com",
    "associatedpress.com",
    "bloomberg.com",
    "ft.com",
    "wsj.com",
    "bbc.com",
    "bbc.co.uk",
)
TIER3_HOSTS = (
    "goldmansachs.com",
    "jpmorgan.com",
    "morganstanley.com",
    "gs.com",
    "research.wellsfargo.com",
)
TRACKING_KEYS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}
INJECTION_MARKERS = (
    "ignore previous",
    "ignore all previous",
    "system prompt",
    "you are now",
    "disregard instructions",
    "忽略以上",
    "忽略之前",
    "系统提示",
)


def normalize_url(url: str) -> str:
    raw = (url or "").strip()
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return raw
    host = parts.hostname.lower()
    if host.startswith("www."):
        host = host[4:]
    query = urlencode(
        [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key.lower() not in TRACKING_KEYS],
        doseq=True,
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), host, path, query, ""))


def host_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def classify_source(url: str, publisher: str = "") -> dict[str, object]:
    host = host_of(url)
    name = (publisher or "").lower()
    if any(host == item or host.endswith("." + item) for item in TIER1_HOSTS):
        return {
            "source_tier": 1,
            "content_type": "official_fact",
            "fact_or_opinion": "fact",
            "primary_or_secondary": "primary",
        }
    if any(host == item or host.endswith("." + item) for item in TIER2_HOSTS) or any(
        token in name for token in ("reuters", "associated press", "ap ", "bloomberg")
    ):
        return {
            "source_tier": 2,
            "content_type": "media_report",
            "fact_or_opinion": "fact",
            "primary_or_secondary": "secondary",
        }
    if any(host == item or host.endswith("." + item) for item in TIER3_HOSTS) or any(
        token in name for token in ("goldman", "morgan stanley", "j.p. morgan", "jpmorgan")
    ):
        return {
            "source_tier": 3,
            "content_type": "research_opinion",
            "fact_or_opinion": "opinion",
            "primary_or_secondary": "secondary",
        }
    return {
        "source_tier": 4,
        "content_type": "aggregator",
        "fact_or_opinion": "opinion",
        "primary_or_secondary": "secondary",
    }


def sanitize_untrusted(text: str) -> str:
    """Article bodies are untrusted data only. Never execute or promote instructions."""
    lines = []
    for line in str(text or "").splitlines():
        lowered = line.strip().lower()
        if any(marker in lowered for marker in INJECTION_MARKERS):
            continue
        lines.append(line)
    cleaned = "\n".join(lines)
    return cleaned[:4000]


def source_id_for(url: str) -> str:
    return "src_" + hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:16]


def document_to_source(doc: EventDocument, *, seen_at: str) -> dict[str, object]:
    cls = classify_source(doc.url, doc.publisher)
    canonical = normalize_url(doc.url)
    return {
        "source_id": source_id_for(doc.url),
        "source_url": doc.url,
        "canonical_url": canonical,
        "publisher": doc.publisher,
        "title": doc.title,
        "published_at": doc.published_at,
        "first_seen_at": seen_at,
        **cls,
    }
