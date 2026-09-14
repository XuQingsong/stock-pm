"""Source tiers, URL normalization, and untrusted-content hygiene."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from stock_pm.config import Settings

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


BLOCKED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "metadata.google.internal",
    "example.com",
    "example.invalid",
    "example.org",
}


def events_data_mode(settings: Settings | None = None) -> str:
    """Production default is empty. Fixtures are never implicit live data."""
    config = settings or Settings()
    explicit = (getattr(config, "events_mode", None) or os.getenv("STOCK_PM_EVENTS_MODE") or "").strip().lower()
    if explicit in {"empty", "live", "demo", "fixture", "test", "recorded_replay", "replay"}:
        if explicit == "test":
            return "fixture"
        if explicit == "replay":
            return "recorded_replay"
        return explicit
    env = (config.app_env or os.getenv("APP_ENV") or "").strip().lower()
    if env in {"test", "development", "local"}:
        return "fixture"
    if os.getenv("PYTEST_CURRENT_TEST"):
        return "fixture"
    return "empty"


def is_safe_public_http_url(url: str) -> bool:
    parts = urlsplit((url or "").strip())
    if parts.scheme not in {"http", "https"}:
        return False
    if parts.username or parts.password:
        return False
    host = (parts.hostname or "").lower()
    if not host or host in BLOCKED_HOSTS or host.endswith(".example.com") or host.endswith(".invalid"):
        return False
    if host.startswith("www."):
        host = host[4:]
        if host in BLOCKED_HOSTS:
            return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast):
        return False
    return True


def redact_url(url: str) -> str:
    parts = urlsplit(url or "")
    if not parts.scheme:
        return "<redacted>"
    query = urlencode(
        [
            (key, "REDACTED" if re.search(r"(key|token|secret|password|cx)", key, re.I) else value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
        ]
    )
    host = (parts.hostname or "").lower()
    return urlunsplit((parts.scheme, host, parts.path, query, ""))


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


APPROVED_TIER1_CONTENT = frozenset({"official_fact", "official_statement", "official_release"})
DISCOVERY_BODY_SOURCES = frozenset({"cse_snippet", "discovery_candidate", "discovery_only"})
DISCOVERY_ROLES = frozenset({"discovery_candidate", "discovery_only"})
STALE_REF_FLAGS = frozenset({"stale", "degraded", "revoked", "superseded"})


def is_tier1_https(url: str) -> bool:
    """True only for HTTPS URLs on the official Tier-1 host allowlist."""
    if not is_safe_public_http_url(url):
        return False
    parts = urlsplit(url)
    if parts.scheme != "https":
        return False
    host = host_of(url)
    return any(host == item or host.endswith("." + item) for item in TIER1_HOSTS)


def _explicit_true(value: object) -> bool:
    return value is True or value in {1, "1", "true", "True"}


def tier1_ref_gaps(ref: dict | None) -> list[str]:
    """Fail-closed gaps for a current primary official Tier-1 original.

    Missing metadata is a failure. Defaults such as 'fact' or tier=1 are not applied.
    """
    if not isinstance(ref, dict) or not ref:
        return ["ref_missing"]
    gaps: list[str] = []
    try:
        tier = int(ref["source_tier"]) if ref.get("source_tier") not in (None, "") else None
    except (TypeError, ValueError, KeyError):
        tier = None
    if tier != 1:
        gaps.append("source_tier")
    if ref.get("fact_or_opinion") != "fact":
        gaps.append("fact_or_opinion")
    if ref.get("primary_or_secondary") != "primary":
        gaps.append("primary_or_secondary")
    if ref.get("content_type") not in APPROVED_TIER1_CONTENT:
        gaps.append("content_type")
    url = str(ref.get("source_url") or ref.get("canonical_url") or "").strip()
    if not is_tier1_https(url):
        gaps.append("official_https_host")
    if not _explicit_true(ref.get("is_current")):
        gaps.append("is_current")
    if any(ref.get(flag) for flag in STALE_REF_FLAGS):
        gaps.append("stale_or_revoked")
    body = str(ref.get("body_source") or "")
    if body in DISCOVERY_BODY_SOURCES:
        gaps.append("discovery_body")
    role = str(ref.get("discovery_role") or "")
    if role in DISCOVERY_ROLES:
        gaps.append("discovery_role")
    return gaps


def is_https_registrable_host(url: str, root: str) -> bool:
    """True only for https and a hostname that is exactly root or a subdomain of root."""
    if not is_safe_public_http_url(url):
        return False
    parts = urlsplit(url)
    if parts.scheme != "https":
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host == root or host.endswith(f".{root}")


def http_redirect_allowed(from_url: str, to_url: str) -> bool:
    """Do not follow official fetches onto a different registrable host or off https."""
    if is_https_registrable_host(from_url, "sec.gov"):
        return is_https_registrable_host(to_url, "sec.gov")
    if is_https_registrable_host(from_url, "eia.gov"):
        return is_https_registrable_host(to_url, "eia.gov")
    if is_https_registrable_host(from_url, "federalreserve.gov"):
        return is_https_registrable_host(to_url, "federalreserve.gov")
    return (
        is_safe_public_http_url(to_url)
        and urlsplit(to_url).scheme == "https"
        and host_of(from_url) == host_of(to_url)
    )


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
            "fact_or_opinion": "reported",
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


def sanitize_untrusted(text: str, *, max_len: int | None = 4000) -> str:
    """Article bodies are untrusted data only. Never execute or promote instructions."""
    lines = []
    for line in str(text or "").splitlines():
        lowered = line.strip().lower()
        if any(marker in lowered for marker in INJECTION_MARKERS):
            continue
        lines.append(line)
    cleaned = "\n".join(lines)
    if max_len is None:
        return cleaned
    return cleaned[:max_len]


def source_id_for(url: str) -> str:
    return "src_" + hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:16]


def is_discovery_snippet(doc: EventDocument | dict[str, object] | None) -> bool:
    """Google CSE (and other search snippets) are discovery entry only."""
    if doc is None:
        return False
    if isinstance(doc, dict):
        body_source = str(doc.get("body_source") or "")
        discovery_role = str(doc.get("discovery_role") or "")
        provider = str(doc.get("provider") or "")
        publisher = str(doc.get("publisher") or "")
    else:
        body_source = str(getattr(doc, "body_source", "") or "")
        discovery_role = str(getattr(doc, "discovery_role", "") or "")
        provider = str(getattr(doc, "provider", "") or "")
        publisher = str(getattr(doc, "publisher", "") or "")
    if body_source == "cse_snippet":
        return True
    if discovery_role in {"discovery_candidate", "discovery_only"}:
        return True
    if provider == "google":
        return True
    return "google cse" in publisher.lower()


def why_trusted(source: dict[str, object] | None = None, **fields: object) -> str:
    """Human-readable trust boundary. Discovery snippets never count as facts."""
    row = dict(source or {})
    row.update({key: value for key, value in fields.items() if value is not None})
    if is_discovery_snippet(row):
        return "Google CSE 只作发现入口，搜索摘要不得作为事实或方向证据"
    tier = int(row.get("source_tier") or 0)
    content = str(row.get("content_type") or "")
    fact = str(row.get("fact_or_opinion") or "")
    if tier == 1 or content == "official_fact":
        return "监管/政府/交易所/公司原文，一级事实来源"
    if tier == 2 or content == "media_report" or fact == "reported":
        return "主流媒体报道，可用于确认，不能替代官方原文，不得标成可替代 Tier1 的事实"
    if tier == 3 or content == "research_opinion" or fact == "opinion":
        return "投行/研究机构观点，必须保留作者、日期与原文链接，不得升级为事实"
    return "聚合转载/无原文，不得进入方向证据"


def document_to_source(doc: EventDocument, *, seen_at: str) -> dict[str, object]:
    from .evidence import infer_document_role, infer_evidence_role

    cls = classify_source(doc.url, doc.publisher)
    discovery = is_discovery_snippet(doc)
    discovery_role = getattr(doc, "discovery_role", None) or ("discovery_candidate" if discovery else None)
    body_source = getattr(doc, "body_source", None) or ("cse_snippet" if discovery else None)
    if discovery:
        cls = {
            "source_tier": 4,
            "content_type": "aggregator",
            "fact_or_opinion": "opinion",
            "primary_or_secondary": "secondary",
        }
        evidence_role = "discovery_candidate"
        document_role = "discovery_candidate"
    else:
        document_role = doc.document_role or infer_document_role(doc.url, doc.title)
        if document_role == "regime_catalog" or doc.evidence_role == "regime_catalog":
            evidence_role = "regime_catalog"
        elif doc.evidence_role in {"association_metadata", "structured_field_bindings"}:
            evidence_role = doc.evidence_role
        else:
            evidence_role = infer_evidence_role(doc.url, document_role)
    payload = {
        "source_id": source_id_for(doc.url),
        "source_url": doc.url,
        "canonical_url": normalize_url(doc.url),
        "publisher": doc.publisher,
        "title": doc.title,
        "published_at": doc.published_at,
        "first_seen_at": seen_at,
        "document_role": document_role,
        "evidence_role": evidence_role,
        "last_fetched_at": getattr(doc, "last_fetched_at", None),
        "body_source": body_source,
        "fetch_error": getattr(doc, "fetch_error", None),
        "filing_items": list(getattr(doc, "filing_items", None) or []),
        "author": getattr(doc, "author", None),
        "discovery_role": discovery_role,
        "next_retry_at": getattr(doc, "next_retry_at", None),
        **cls,
    }
    payload["why_trusted"] = why_trusted(payload)
    return payload
