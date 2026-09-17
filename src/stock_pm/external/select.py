"""Keep 20–40 decision-useful documents. Archive the rest."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .clients import within_days
from .quality import source_tier
from .types import NEWS_WINDOW_DAYS


REASONING_DOC_MAX = 40
COUNTER_MARKERS = re.compile(
    r"\b(risk|delay|shortage|cut|slowdown|weak|decline|miss|cancel|constraint|headwind|tariff|ban)\b",
    re.I,
)


def slim_fact(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "fact": row.get("fact"),
        "source_url": row.get("source_url") or row.get("url"),
        "source_time": row.get("source_time") or row.get("published_at"),
        "source_tier": row.get("source_tier"),
        "claim_title": row.get("claim_title"),
        "source": row.get("source") or row.get("source_family"),
        "document_id": row.get("document_id"),
    }


def _tier(row: dict[str, Any]) -> int:
    return int(row.get("source_tier") or source_tier(row.get("url")) or 5)


def _date_rank(row: dict[str, Any]) -> int:
    text = str(row.get("published_at") or "")[:10]
    if not text:
        return 0
    try:
        return datetime.strptime(text, "%Y-%m-%d").toordinal()
    except ValueError:
        return 0


def _keep_key(row: dict[str, Any]) -> tuple[int, int, int, int, int]:
    return (
        0 if row.get("is_primary_source") or _tier(row) == 1 else 1,
        _tier(row),
        0 if row.get("is_dated") else 1,
        -_date_rank(row),
        -len(str(row.get("clean_text") or "")),
    )


def tier_counts(docs: list[dict[str, Any]]) -> dict[str, int]:
    out = {"tier1": 0, "tier2": 0, "tier3": 0, "tier4": 0, "tier5": 0}
    for row in docs:
        key = f"tier{min(5, max(1, _tier(row)))}"
        out[key] = out.get(key, 0) + 1
    return out


def select_reasoning_documents(
    docs: list[dict[str, Any]],
    *,
    days: int = NEWS_WINDOW_DAYS,
    max_docs: int = REASONING_DOC_MAX,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Return (retained, archived, stats). Prefer official and dated independent sources."""
    non_macro = [row for row in docs if str(row.get("source_type") or "") != "macro"]
    macro = [row for row in docs if str(row.get("source_type") or "") == "macro"]
    buckets: dict[int, list[dict[str, Any]]] = {1: [], 2: [], 3: [], 4: [], 5: []}
    for row in non_macro:
        buckets[_tier(row)].append(row)
    for key in buckets:
        buckets[key].sort(key=_keep_key)

    kept: list[dict[str, Any]] = []
    kept.extend(buckets[1][:12])
    kept.extend([row for row in buckets[2] if row.get("is_dated") or within_days(row.get("published_at"), days)][:10])
    kept.extend([row for row in buckets[3] if row.get("is_dated")][:8])
    primary = sum(1 for row in kept if _tier(row) <= 2)
    if primary < 8:
        kept.extend([row for row in buckets[4] if row.get("is_dated") and row.get("is_full_text")][:6])
    if len(kept) < 6:
        kept.extend(buckets[5][:2])
    kept.extend(macro[:4])

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in kept:
        key = str(row.get("canonical_url") or row.get("url") or row.get("document_id") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        unique.append(row)
        if len(unique) >= max_docs:
            break
    kept_ids = {str(item.get("document_id") or item.get("canonical_url") or item.get("url")) for item in unique}
    archived = [row for row in docs if str(row.get("document_id") or row.get("canonical_url") or row.get("url")) not in kept_ids]
    before = tier_counts(docs)
    after = tier_counts(unique)
    stats = {
        "discovered_docs": len(docs),
        "retained_for_reasoning": len(unique),
        "archived_docs": len(archived),
        "tier_distribution_before": before,
        "tier_distribution_after": after,
        "primary_source_count": sum(1 for row in unique if _tier(row) == 1),
        "independent_source_count": sum(1 for row in unique if _tier(row) == 2),
        "industry_source_count": sum(
            1 for row in unique if _tier(row) == 3 or row.get("source_type") == "industry"
        ),
        "tier45_filtered_count": (before.get("tier4") or 0) + (before.get("tier5") or 0) - (after.get("tier4") or 0) - (after.get("tier5") or 0),
    }
    return unique, archived, stats


def docs_for_extraction(retained: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """If official + independent coverage is enough, do not extract Tier 4 repeats."""
    usable = [row for row in retained if row.get("is_full_text") and str(row.get("source_type") or "") != "macro"]
    primary = [row for row in usable if _tier(row) <= 2]
    if len(primary) >= 6:
        return [row for row in usable if _tier(row) <= 3]
    return [row for row in usable if _tier(row) <= 4]


def compress_reasoning_context(
    retained: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    *,
    archived: list[dict[str, Any]] | None = None,
    ticker: str = "",
    research_leads: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from .evidence_set import build_evidence_set

    return build_evidence_set(
        retained,
        facts,
        claims,
        archived=archived,
        ticker=ticker,
        research_leads=research_leads,
    )
