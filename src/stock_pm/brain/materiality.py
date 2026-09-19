"""Materiality gate: should GLM-5.3 think about this event?"""

from __future__ import annotations

from typing import Any

from .knowledge import classify_information, decision_materiality
from .shadow import should_enter_shadow

_LOW_VALUE = (
    "product launch",
    "launches new",
    "t-shirt",
    "merch",
    "branded apparel",
    "conference appearance",
    "keynote photo",
    "appointed",
    "hires",
    "hiring",
    "promoted to",
    "no new information",
    "analyst recap",
    "what analysts are saying",
    "roundup",
    "stock to watch",
    "price target",
)
_MATERIAL_HINTS = (
    "customer",
    "order",
    "design win",
    "capex",
    "guidance",
    "earnings",
    "demand",
    "cancel",
    "reduction",
    "hyperscaler",
    "regulation",
    "acquire",
    "merger",
)


def _relative_vs_peers(row: dict[str, Any] | None) -> float:
    item = row or {}
    try:
        issuer = float(item.get("price_change_pct"))
    except (TypeError, ValueError):
        return 0.0
    peers = item.get("peers") or item.get("peer_moves") or {}
    values: list[float] = []
    for value in (peers.values() if isinstance(peers, dict) else []):
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    if not values:
        return 0.0
    avg = sum(values) / len(values)
    return abs(issuer - avg)


def _blob(row: dict[str, Any] | None) -> str:
    item = row or {}
    return f"{item.get('title') or ''} {item.get('fact') or ''} {item.get('statement') or ''} {item.get('new_fact') or ''}".lower()


def materiality_gate(
    item: dict[str, Any] | None,
    *,
    ticker: str,
    extract: dict[str, Any] | None = None,
    drivers: list[dict[str, Any]] | None = None,
    claims: list[dict[str, Any]] | None = None,
    related_entities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    row = dict(item or {})
    extracted = dict(extract or {})
    blob = _blob({**row, **extracted})
    classified = classify_information(row, ticker=ticker, related_entities=related_entities, drivers=drivers, claims=claims)
    low_value = any(token in blob for token in _LOW_VALUE)
    explicit = extracted.get("material")
    try:
        tape_move = abs(float(row.get("price_change_pct")))
    except (TypeError, ValueError):
        tape_move = 0.0
    relative_move = _relative_vs_peers(row)
    abnormal_price = tape_move >= 5 or relative_move >= 4
    announcement = any(token in blob for token in _MATERIAL_HINTS) or str(row.get("event_type") or "") in {
        "earnings",
        "guidance",
        "customer",
        "competition",
        "mna",
        "regulation",
    }
    kind = str(row.get("kind") or extracted.get("kind") or "")
    price_only = (kind == "price" or (abnormal_price and not announcement)) and not announcement
    if abnormal_price:
        material = True
        reason = "Abnormal Price Observation requires market-layer interpretation."
    elif explicit is False or str(extracted.get("novelty") or "") in {"repeat", "none"}:
        material = False
        reason = "L1 marked the item non-material or not new."
    elif low_value and not any(token in blob for token in _MATERIAL_HINTS):
        material = False
        reason = "Low-value news does not justify GLM-5.3 reasoning."
    elif should_enter_shadow(row) or str(extracted.get("fact_reliability") or row.get("fact_reliability") or "") == "rumor":
        material = True
        reason = "Unconfirmed but potentially material; GLM-5.3 may only propose Shadow State / Research Questions."
    elif explicit is True or str(classified.get("decision_materiality") or decision_materiality(row, drivers=drivers, claims=claims)) == "material":
        material = True
        reason = "Material operating or customer information."
    elif any(token in blob for token in _MATERIAL_HINTS):
        material = True
        reason = "Event type is decision-relevant."
    else:
        material = False
        reason = "No new decision-relevant information."
    affected = list(extracted.get("possible_affected") or extracted.get("affected_objects") or [])
    return {
        "material": bool(material),
        "reason": reason,
        "possible_affected_objects": [str(item) for item in affected if str(item).strip()],
        "layer": classified.get("layer"),
        "fact_reliability": classified.get("fact_reliability"),
        "novelty": extracted.get("novelty") or row.get("novelty"),
        "abnormal_price": bool(abnormal_price),
        "price_only": bool(price_only and material),
        "tape_move": tape_move,
        "relative_move": relative_move,
    }
