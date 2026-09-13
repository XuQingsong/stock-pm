"""Evidence roles, publisher identity, and claim-support checks.

Accept-only host lists stay in the accept script. These helpers do not
change which live feeds production may fetch.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from .types import EventClaim, EventSource, TrustedEvent


STOP = frozenset(
    "the a an of to for in on and or as by with from after before over under about vs versus "
    "this that with from into amid after through will than then also more most "
    "federal reserve board committee meeting release releases issues expects updates "
    "increases forecast forecasts global".split()
)

PUBLISHER_ALIASES = {
    "federal reserve board": "federal_reserve",
    "federal reserve": "federal_reserve",
    "the fed": "federal_reserve",
    "u s energy information administration": "eia",
    "energy information administration": "eia",
    "eia": "eia",
    "u s department of the treasury ofac": "ofac",
    "u s department of the treasury": "treasury",
    "office of foreign assets control": "ofac",
    "sec edgar": "sec",
    "reuters": "reuters",
    "associated press": "associated_press",
}

PHASE_LABELS = {
    "disruption": "中断",
    "demand_buffer": "需求缓冲",
    "reopen_supply": "重开/供应恢复",
}


def publisher_key(publisher: str, url: str = "") -> str:
    host = (urlsplit(url or "").hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host.endswith("federalreserve.gov"):
        return "federal_reserve"
    if host.endswith("eia.gov"):
        return "eia"
    if host.endswith("sec.gov"):
        return "sec"
    if host.endswith("ofac.treasury.gov"):
        return "ofac"
    if host.endswith("treasury.gov") or host.endswith("home.treasury.gov"):
        return "treasury"
    if host.endswith("reuters.com"):
        return "reuters"
    if host.endswith("apnews.com") or host.endswith("associatedpress.com"):
        return "associated_press"
    normalized = re.sub(r"[^a-z0-9]+", " ", (publisher or "").lower()).strip()
    return PUBLISHER_ALIASES.get(normalized, normalized or host or "unknown")


def infer_document_role(url: str, title: str = "") -> str | None:
    path = (urlsplit(url or "").path or "").lower()
    text = f"{path} {title or ''}".lower()
    if "sanctions-programs-and-country-information" in path:
        return "regime_catalog"
    if "fomcminutes" in path or "minutes of the federal open market" in text:
        return "minutes"
    if "economic projections" in text or re.search(r"monetary\d{8}b\.htm", path):
        return "projections"
    if "fomc statement" in text or re.search(r"monetary\d{8}a\.htm", path):
        return "statement"
    if "/pressroom/releases/" in path:
        return "forecast_update"
    return None


def infer_evidence_role(url: str, document_role: str | None = None) -> str:
    role = document_role or infer_document_role(url)
    if role == "regime_catalog":
        return "regime_catalog"
    return "event_fact"


def infer_phase(text: str) -> str | None:
    blob = (text or "").lower()
    if ("opening of the strait" in blob or "opening of the strait of hormuz" in blob) or (
        "重开" in blob or ("opening" in blob and "hormuz" in blob and "production" in blob)
    ):
        return "reopen_supply"
    if "demand" in blob and ("limit" in blob or "缓冲" in blob):
        return "demand_buffer"
    if "disruption" in blob or "中断" in blob:
        return "disruption"
    return None


def excerpt_supports_claim(claim: str, excerpt: str, title: str = "", *, required: list[str] | None = None) -> bool:
    """True when the original title/excerpt semantically supports the claim."""
    hay = f"{title or ''} {excerpt or ''}".lower()
    if not hay.strip():
        return False
    if required:
        return all(token.lower() in hay for token in required if token)
    tokens = [word for word in re.findall(r"[a-z0-9\u4e00-\u9fff]{4,}", (claim or "").lower()) if word not in STOP]
    if not tokens:
        return bool((title or "").strip())
    hits = sum(1 for token in tokens if token in hay)
    return hits >= max(2, min(3, (len(tokens) + 1) // 2))


def current_claims(event: TrustedEvent) -> list[EventClaim]:
    return [row for row in event.claims if row.status not in {"superseded", "revoked"}]


def source_metrics(sources: list[EventSource], claims: list[EventClaim] | None = None) -> dict[str, Any]:
    publishers = {publisher_key(row.publisher, row.source_url) for row in sources}
    fact_sources = [row for row in sources if getattr(row, "evidence_role", "event_fact") == "event_fact"]
    fact_publishers = {publisher_key(row.publisher, row.source_url) for row in fact_sources}
    superseded = [row for row in (claims or []) if row.status == "superseded"]
    return {
        "document_count": len(sources),
        "publisher_count": len(publishers),
        "independent_publisher_count": len(fact_publishers),
        "superseded_count": len(superseded),
        "document_roles": sorted({str(row.document_role) for row in sources if getattr(row, "document_role", None)}),
    }


def evolution_path(event: TrustedEvent) -> list[str]:
    seen: list[str] = []
    for row in event.timeline:
        phase = row.get("phase")
        label = PHASE_LABELS.get(str(phase) if phase else "", "")
        if label and label not in seen:
            seen.append(label)
    if not seen:
        for claim in event.claims:
            phase = infer_phase(claim.text)
            label = PHASE_LABELS.get(phase or "", "")
            if label and label not in seen:
                seen.append(label)
    return seen
