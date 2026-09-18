"""Value Driver identity, normalization, and universe selection.

Drivers are long-lived objects. A reported print is not a driver.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from stock_pm.research.ids import new_id
from stock_pm.research.llm_reason import compact_text

from .claim_integrity import is_fact_restatement
from .limits import limit_words
from .types import (
    CONFIDENCE,
    DRIVER_CATEGORIES,
    DRIVER_STATUSES,
    DRIVER_UNIVERSE_MAX,
    DRIVER_UNIVERSE_MIN,
    HORIZONS,
    IMPORTANCE,
)

_RANK = {"high": 3, "medium": 2, "low": 1, "": 0}
_PRINT_NAME = re.compile(
    r"\b(revenue|eps|earnings|sales|profit|net income)\b.{0,40}"
    r"\b(grew|rose|fell|increased|decreased|was|were|is|are)\b.{0,24}"
    r"(\d|\$|%|percent)",
    re.I,
)


def _norm_key(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    return text.strip("_")[:80]


def make_canonical_key(raw: dict[str, Any]) -> str:
    explicit = _norm_key(raw.get("canonical_key") or "")
    if explicit:
        return explicit
    return _norm_key(raw.get("name") or raw.get("title") or "unspecified") or "unspecified"


def make_driver_key(ticker: str, canonical_key: str) -> str:
    blob = f"{str(ticker or '').upper()}|{_norm_key(canonical_key)}"
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]
    return f"bdk_{digest}"


def is_print_restatement(name: str, description: str = "") -> bool:
    parts = [str(name or "").strip(), str(description or "").strip()]
    blob = " ".join(part for part in parts if part)
    if not blob:
        return True
    if is_fact_restatement(blob):
        return True
    if parts[0] and is_fact_restatement(parts[0]):
        return True
    if parts[1] and is_fact_restatement(parts[1]):
        return True
    return bool(_PRINT_NAME.search(blob))


def score_driver(row: dict[str, Any]) -> int:
    return (
        _RANK.get(str(row.get("importance") or ""), 0) * 4
        + _RANK.get(str(row.get("uncertainty") or ""), 0) * 3
        + _RANK.get(str(row.get("persistence") or ""), 0) * 2
        + _RANK.get(str((row.get("scores") or {}).get("decision_relevance") or row.get("decision_relevance") or ""), 0)
    )


def normalize_driver(
    raw: dict[str, Any],
    *,
    ticker: str,
    allowed_ids: set[str],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    name = limit_words(compact_text(raw.get("name") or raw.get("title") or "", 160), 12)
    description = limit_words(compact_text(raw.get("description") or "", 600), 80)
    why = limit_words(compact_text(raw.get("why_it_matters") or "", 600), 80)
    if not name:
        return None
    if is_print_restatement(name, description):
        return None
    canonical = make_canonical_key({**raw, "name": name})
    if canonical.replace("_", " ") and is_print_restatement(canonical.replace("_", " ")):
        return None
    category = str(raw.get("category") or "").strip().lower()
    if category not in DRIVER_CATEGORIES:
        blob = f"{name} {description} {canonical}".lower()
        category = _infer_category(blob)
    evidence_ids = []
    for item in raw.get("evidence_ids") or []:
        key = str(item or "").strip()
        if key and key in allowed_ids and key not in evidence_ids:
            evidence_ids.append(key)
    if not evidence_ids:
        return None
    importance = str(raw.get("importance") or "medium")
    if importance not in IMPORTANCE:
        importance = "medium"
    uncertainty = str(raw.get("uncertainty") or "medium")
    if uncertainty not in CONFIDENCE:
        uncertainty = "medium"
    persistence = str(raw.get("persistence") or "medium")
    if persistence not in CONFIDENCE:
        persistence = "medium"
    horizon = raw.get("time_horizon")
    if horizon not in HORIZONS:
        horizon = "medium"
    status = str(raw.get("status") or "active")
    if status not in DRIVER_STATUSES:
        status = "active"
    related_claim_ids = [str(item) for item in (raw.get("related_claim_ids") or []) if str(item).strip()]
    related_entity_ids = [str(item) for item in (raw.get("related_entity_ids") or []) if str(item).strip()]
    missing = [limit_words(compact_text(item, 160), 24) for item in (raw.get("missing_evidence") or []) if str(item).strip()][:6]
    driver_id = (existing or {}).get("driver_id") or raw.get("driver_id") or new_id("bdrv")
    return {
        "driver_id": driver_id,
        "ticker": str(ticker or "").upper(),
        "canonical_key": canonical,
        "driver_key": make_driver_key(ticker, canonical),
        "name": name,
        "description": description,
        "category": category,
        "financial_link": compact_text(raw.get("financial_link") or "", 80) or None,
        "time_horizon": horizon,
        "current_state": limit_words(compact_text(raw.get("current_state") or "", 400), 40),
        "direction": compact_text(raw.get("direction") or "", 40) or None,
        "importance": importance,
        "uncertainty": uncertainty,
        "persistence": persistence,
        "reversibility": compact_text(raw.get("reversibility") or "", 40) or None,
        "why_it_matters": why,
        "evidence_ids": evidence_ids,
        "related_claim_ids": related_claim_ids,
        "related_entity_ids": related_entity_ids,
        "missing_evidence": [item for item in missing if item],
        "status": status,
        "match_action": "update_existing" if existing else "create_new",
    }


def _infer_category(blob: str) -> str:
    mapping = (
        ("customer_concentration", ("concentration", "customer share", "top customer")),
        ("pricing", ("pricing power", "asp", "price")),
        ("margin", ("margin", "mix")),
        ("market_share", ("market share", "share loss", "share gain")),
        ("capacity", ("capacity", "utilization", "bottleneck")),
        ("competition", ("competitor", "asic", "internal design", "displacement")),
        ("technology", ("node", "process", "cpo", "800g", "1.6t", "custom silicon")),
        ("regulation", ("regulation", "dma", "antitrust", "app store")),
        ("macro", ("rates", "fx", "macro", "recession")),
        ("capital_allocation", ("buyback", "m&a", "dividend", "capex allocation")),
        ("accounting_quality", ("accounting", "accrual", "one-off")),
        ("valuation", ("multiple", "valuation", "wacc", "terminal")),
        ("supplier_dependency", ("supplier", "foundry", "tsmc")),
        ("volume", ("unit", "volume", "shipments")),
        ("product_mix", ("mix", "segment mix")),
        ("demand", ("demand", "duration", "durability", "growth")),
    )
    for category, tokens in mapping:
        if any(token in blob for token in tokens):
            return category
    return "demand"


def match_existing_driver(item: dict[str, Any], existing: list[dict[str, Any]]) -> dict[str, Any] | None:
    key = str(item.get("canonical_key") or "")
    driver_key = str(item.get("driver_key") or "")
    for row in existing or []:
        if key and row.get("canonical_key") == key:
            return row
        if driver_key and row.get("driver_key") == driver_key:
            return row
    return None


def select_driver_universe(
    raw_drivers: list[dict[str, Any]],
    *,
    ticker: str,
    allowed_ids: set[str],
    existing: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep 8–15 material drivers with stable identity. Reject print restatements."""
    prior = list(existing or [])
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_drivers or []:
        if not isinstance(raw, dict):
            continue
        match = match_existing_driver(
            {"canonical_key": make_canonical_key(raw), "driver_key": make_driver_key(ticker, make_canonical_key(raw))},
            prior,
        )
        item = normalize_driver(raw, ticker=ticker, allowed_ids=allowed_ids, existing=match)
        if not item:
            rejected.append(
                {
                    "name": raw.get("name") or raw.get("title"),
                    "reason": "print_restatement_or_ungrounded",
                }
            )
            continue
        if item["canonical_key"] in seen:
            continue
        seen.add(item["canonical_key"])
        kept.append(item)
    kept.sort(key=score_driver, reverse=True)
    extra = kept[DRIVER_UNIVERSE_MAX:]
    kept = kept[:DRIVER_UNIVERSE_MAX]
    for row in extra:
        rejected.append({"name": row.get("name"), "canonical_key": row.get("canonical_key"), "reason": "over_universe_cap"})
    return kept, rejected


def claims_require_drivers(core: list[dict[str, Any]], drivers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Core claims must bind to a driver in the current universe."""
    by_id = {str(row.get("driver_id")): row for row in drivers if row.get("driver_id")}
    by_key = {str(row.get("canonical_key")): row for row in drivers if row.get("canonical_key")}
    out: list[dict[str, Any]] = []
    for item in core:
        bound: list[str] = []
        for token in item.get("related_driver_ids") or []:
            key = str(token or "").strip()
            if key in by_id:
                bound.append(key)
            elif key in by_key:
                bound.append(str(by_key[key]["driver_id"]))
        if not bound:
            subject = str(item.get("claim_subject") or "")
            dimension = str(item.get("claim_dimension") or "")
            blob = f"{item.get('title') or ''} {item.get('statement') or ''} {subject} {dimension}".lower()
            for row in drivers:
                hay = f"{row.get('canonical_key')} {row.get('name')} {row.get('category')} {row.get('description')}".lower()
                if subject and subject.replace("_", " ") in hay:
                    bound.append(str(row["driver_id"]))
                    break
                if any(token and token in hay for token in (dimension.replace("_", " "), str(row.get("category") or ""))):
                    if any(part in blob for part in hay.split()[:3]):
                        bound.append(str(row["driver_id"]))
                        break
        if not bound:
            item = dict(item)
            item["selected_as_core"] = False
            item["is_core"] = False
            item["why_not_core"] = item.get("why_not_core") or "Core Claim must bind to a Value Driver."
            continue
        item = dict(item)
        item["related_driver_ids"] = list(dict.fromkeys(bound))
        out.append(item)
    return out
