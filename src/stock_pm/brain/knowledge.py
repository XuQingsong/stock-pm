"""Three-layer knowledge filter: source quality, fact reliability, decision materiality.

SEC/issuer origin does not automatically make a fact decision-material.
"""

from __future__ import annotations

import re
from typing import Any

from .claim_integrity import classify_source_relationship
from .types import FACT_RELIABILITY, KNOWLEDGE_LAYERS

_RUMOR = re.compile(r"\b(rumor|unconfirmed|reportedly|sources say|might|could be)\b", re.I)
_OPINION = re.compile(r"\b(we believe|in our view|bullish|bearish|overweight|underweight|price target)\b", re.I)
_ESTIMATE = re.compile(r"\b(consensus|estimate|forecast|model implies|we estimate)\b", re.I)


def fact_reliability(row: dict[str, Any] | None) -> str:
    item = row or {}
    explicit = str(item.get("reliability") or item.get("fact_reliability") or "")
    if explicit in FACT_RELIABILITY:
        return explicit
    source_type = str(item.get("source_type") or "").lower()
    blob = f"{item.get('fact') or ''} {item.get('excerpt') or ''} {item.get('title') or ''}"
    if _RUMOR.search(blob):
        return "rumor"
    if _OPINION.search(blob):
        return "opinion"
    if _ESTIMATE.search(blob) or source_type in {"analyst", "model"}:
        return "estimate"
    if source_type in {"sec_filing", "filing", "earnings_release", "official_document", "exhibit", "transcript"}:
        return "direct_fact"
    if str(item.get("extraction") or "") == "deterministic" or item.get("is_full_text"):
        return "direct_fact"
    if source_type in {"web_search", "news"}:
        return "signal"
    return "derived_fact"


def decision_targets(row: dict[str, Any] | None, *, drivers: list[dict[str, Any]] | None = None, claims: list[dict[str, Any]] | None = None) -> list[str]:
    item = row or {}
    blob = f"{item.get('fact') or ''} {item.get('title') or ''} {item.get('new_fact') or ''} {item.get('statement') or ''}".lower()
    targets: list[str] = []
    if any(token in blob for token in ("guidance", "outlook", "capex", "demand", "share", "margin", "pricing", "customer")):
        targets.append("state")
        targets.append("driver")
    if claims:
        for claim in claims:
            hay = f"{claim.get('title') or ''} {claim.get('statement') or ''} {claim.get('claim_subject') or ''}".lower()
            if hay and any(token and token in blob for token in hay.split()[:6]):
                targets.append("claim")
                break
    if any(token in blob for token in ("revenue", "margin", "opex", "capex", "fcf", "eps", "asp")):
        targets.append("financial")
    if any(token in blob for token in ("scenario", "downside", "upside", "bear", "bull")):
        targets.append("scenario")
    if any(token in blob for token in ("multiple", "valuation", "wacc", "terminal")):
        targets.append("valuation")
    if drivers and "driver" not in targets:
        for driver in drivers:
            key = str(driver.get("canonical_key") or "").replace("_", " ")
            if key and key in blob:
                targets.append("driver")
                break
    return list(dict.fromkeys(targets))


def decision_materiality(
    row: dict[str, Any] | None,
    *,
    drivers: list[dict[str, Any]] | None = None,
    claims: list[dict[str, Any]] | None = None,
) -> str:
    explicit = str((row or {}).get("layer") or "").lower()
    if explicit in {"material", "contextual", "noise"}:
        return "context" if explicit == "contextual" else explicit
    targets = decision_targets(row, drivers=drivers, claims=claims)
    if not targets:
        reliability = fact_reliability(row)
        if reliability in {"opinion", "rumor"}:
            return "noise"
        return "context"
    if fact_reliability(row) in {"rumor", "opinion"} and "claim" not in targets:
        return "context"
    if any(item in targets for item in ("driver", "claim", "financial", "valuation", "scenario", "state")):
        return "material"
    return "context"


def classify_information(
    row: dict[str, Any] | None,
    *,
    ticker: str,
    related_entities: list[dict[str, Any]] | None = None,
    drivers: list[dict[str, Any]] | None = None,
    claims: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    item = row or {}
    source = classify_source_relationship(item, ticker=ticker, related_entities=related_entities)
    reliability = fact_reliability(item)
    materiality = decision_materiality(item, drivers=drivers, claims=claims)
    layer = materiality if materiality in KNOWLEDGE_LAYERS else "context"
    # High-quality origin is not sufficient by itself.
    if source in {"issuer_primary", "related_entity_primary"} and not decision_targets(item, drivers=drivers, claims=claims):
        layer = "context"
        materiality = "context"
    return {
        "source_quality": source,
        "fact_reliability": reliability,
        "decision_materiality": materiality,
        "decision_targets": decision_targets(item, drivers=drivers, claims=claims),
        "layer": layer,
    }
