"""Evidence roles, publisher identity, and claim-support checks.

Accept-only host lists stay in the accept script. These helpers do not
change which live feeds production may fetch.
"""

from __future__ import annotations

import hashlib
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


CHROME_LINE_RE = re.compile(
    r"(?i)^(skip to|an official website|official websites use|secure \.gov|"
    r"here'?s how you know|share sensitive|stay connected|subscribe to|"
    r"menu$|search$|press room$|glossary|statistics$|analysis$|tools$|"
    r"education$|news$|enter search|overview$|press releases$|testimony$|"
    r"presentations$|radio -->|back to home|chapters -->|events$|recent postings|"
    r"u\.s\. energy information administration - eia|"
    r"federal reserve (facebook|instagram|youtube|flickr|linkedin|threads|x page|bluesky)|"
    r"board of governors of the federal reserve system$)"
)
SPACE_RE = re.compile(r"\s+")


def normalize_evidence_text(text: str) -> str:
    return SPACE_RE.sub(" ", str(text or "")).strip()


def drop_chrome_lines(text: str) -> str:
    kept = []
    for line in str(text or "").splitlines():
        collapsed = SPACE_RE.sub(" ", line).strip()
        if collapsed and not CHROME_LINE_RE.match(collapsed):
            kept.append(collapsed)
    return "\n".join(kept)


def _token_spans(text: str, token: str) -> list[tuple[int, int]]:
    hay = text.lower()
    needle = token.lower()
    spans: list[tuple[int, int]] = []
    start = 0
    while needle:
        index = hay.find(needle, start)
        if index < 0:
            break
        spans.append((index, index + len(needle)))
        start = index + 1
    return spans


def select_claim_support_excerpt(
    body: str,
    required: list[str],
    *,
    pad: int = 16,
    max_len: int = 480,
) -> dict[str, Any]:
    """Pick the smallest cleaned-body window that contains every required token.

    Recording must fail when the body does not contain the tokens. Title/HTTP
    status cannot substitute for this window.
    """
    tokens = [item.strip() for item in required if str(item).strip()]
    if not tokens:
        raise ValueError("required_tokens_missing")
    cleaned = normalize_evidence_text(body)
    if not cleaned:
        raise ValueError("empty_body")
    dechromed = normalize_evidence_text(drop_chrome_lines(body))
    search_text = dechromed if dechromed and all(_token_spans(dechromed, token) for token in tokens) else cleaned
    events: list[tuple[int, int, int]] = []
    for index, token in enumerate(tokens):
        spans = _token_spans(search_text, token)
        if not spans:
            raise ValueError(f"token_not_found:{token}")
        events.extend((start, end, index) for start, end in spans)
    events.sort()
    counts = [0] * len(tokens)
    have = 0
    left = 0
    best: tuple[int, int] | None = None
    for right, (_start, end, kind) in enumerate(events):
        if counts[kind] == 0:
            have += 1
        counts[kind] += 1
        while have == len(tokens) and left <= right:
            window = (events[left][0], end)
            if best is None or window[1] - window[0] < best[1] - best[0]:
                best = window
            left_kind = events[left][2]
            counts[left_kind] -= 1
            if counts[left_kind] == 0:
                have -= 1
            left += 1
    if best is None:
        raise ValueError("tokens_not_coverable")
    start = max(0, best[0] - pad)
    end = min(len(search_text), best[1] + pad)
    while start > 0 and not search_text[start - 1].isspace():
        start -= 1
    while end < len(search_text) and not search_text[end : end + 1].isspace():
        end += 1
    excerpt = normalize_evidence_text(search_text[start:end])
    if len(excerpt) > max_len:
        excerpt = normalize_evidence_text(search_text[best[0] : best[1]])
    locate = cleaned.lower().find(excerpt.lower())
    if locate < 0:
        locate = search_text.lower().find(excerpt.lower())
    if locate < 0:
        raise ValueError("excerpt_not_locatable")
    if not excerpt_supports_claim("", excerpt, required=tokens):
        raise ValueError("excerpt_missing_required_tokens")
    return {
        "claim_support_excerpt": excerpt,
        "excerpt_start": locate,
        "excerpt_end": locate + len(excerpt),
        "body_hash": hashlib.sha256(cleaned.encode("utf-8")).hexdigest(),
        "search_len": len(cleaned),
    }


def excerpt_supports_claim(claim: str, excerpt: str, title: str = "", *, required: list[str] | None = None) -> bool:
    """True only when the stored evidence excerpt supports the claim.

    Title, URL, and HTTP 200 do not count. The unused title argument stays for
    call-site compatibility and is ignored.
    """
    del title
    hay = (excerpt or "").lower()
    if not hay.strip():
        return False
    if required:
        return all(token.lower() in hay for token in required if token)
    tokens = [word for word in re.findall(r"[a-z0-9\u4e00-\u9fff]{4,}", (claim or "").lower()) if word not in STOP]
    if not tokens:
        return False
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
