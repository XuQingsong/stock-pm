"""L0 deterministic ingest. No LLM."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from stock_pm.external.quality import source_tier
from stock_pm.research.llm_reason import compact_text

from .claim_integrity import classify_source_relationship, news_is_duplicate
from .events import infer_event_type, make_event_fingerprint
from .knowledge import fact_reliability
from .phase0 import _observation_identity
from .types import NEWS_WINDOW_DAYS

_NUMBER = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?%?")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _parse_stamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            stamp = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def validate_numbers(row: dict[str, Any] | None) -> dict[str, Any]:
    blob = f"{(row or {}).get('title') or ''} {(row or {}).get('fact') or ''} {(row or {}).get('statement') or ''}"
    found = _NUMBER.findall(blob)
    parsed: list[str] = []
    invalid: list[str] = []
    for token in found:
        try:
            float(token.replace(",", "").replace("%", ""))
            parsed.append(token)
        except ValueError:
            invalid.append(token)
    return {"numbers": parsed, "invalid": invalid, "ok": not invalid}


def validate_evidence_ids(row: dict[str, Any] | None, *, allowed_ids: set[str] | None = None) -> list[str]:
    allowed = allowed_ids or set()
    kept: list[str] = []
    for item in (row or {}).get("evidence_ids") or []:
        key = str(item or "").strip()
        if not key:
            continue
        if allowed and key not in allowed:
            continue
        if key not in kept:
            kept.append(key)
    extra = str((row or {}).get("evidence_id") or "").strip()
    if extra and (not allowed or extra in allowed) and extra not in kept:
        kept.append(extra)
    return kept


def process_l0(
    raw: dict[str, Any] | None,
    *,
    ticker: str,
    existing_facts: list[str] | None = None,
    fingerprints: list[str] | None = None,
    identities: list[str] | None = None,
    allowed_ids: set[str] | None = None,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    item = dict(raw or {})
    symbol = str(ticker).upper()
    title = compact_text(item.get("title") or item.get("fact") or item.get("statement") or "", 160)
    identity = _observation_identity(item)
    fingerprint = item.get("fingerprint") or make_event_fingerprint(
        {"title": title, "url": item.get("url") or item.get("source_url"), "subject": item.get("subject") or title}
    )
    facts = list(existing_facts or [])
    seen_fp = list(fingerprints or [])
    seen_id = list(identities or [])
    duplicate = bool(
        item.get("duplicate")
        or fingerprint in seen_fp
        or identity in seen_id
        or news_is_duplicate(item, facts)
    )
    stamp = _parse_stamp(item.get("published_at") or item.get("source_time") or item.get("event_date"))
    stale = bool(stamp and stamp < _now() - timedelta(days=NEWS_WINDOW_DAYS))
    numbers = validate_numbers(item)
    evidence_ids = validate_evidence_ids(item, allowed_ids=allowed_ids)
    source = classify_source_relationship(item, ticker=symbol)
    tier = int(item.get("source_tier") or source_tier(item.get("url") or item.get("source_url"), source=item.get("source")) or 9)
    event_type = str(item.get("event_type") or infer_event_type(item))
    history_hits = [
        row
        for row in (history or [])
        if (fingerprint and str(row.get("object_id") or "") == fingerprint)
        or (title and title.lower()[:40] in f"{row.get('reason') or ''} {row.get('to_payload') or ''}".lower())
    ]
    stop = duplicate
    return {
        "ticker": symbol,
        "title": title,
        "identity": identity,
        "fingerprint": fingerprint,
        "event_hash": fingerprint,
        "duplicate": duplicate,
        "stop": stop,
        "stop_reason": "duplicate" if duplicate else None,
        "stale": stale,
        "source_relationship": source,
        "source_tier": tier,
        "event_type": event_type,
        "fact_reliability": item.get("fact_reliability") or fact_reliability(item),
        "evidence_ids": evidence_ids,
        "numbers": numbers,
        "history_hits": history_hits[:5],
        "item": {
            **item,
            "ticker": symbol,
            "title": title,
            "fingerprint": fingerprint,
            "event_type": event_type,
            "source_relationship": source,
            "source_tier": tier,
            "evidence_ids": evidence_ids,
        },
        "llm_called": False,
    }
