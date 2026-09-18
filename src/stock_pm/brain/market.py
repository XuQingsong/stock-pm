"""Thin market layer: what the tape appears to be trading.

Not a Market Driver engine, Expectation State system, or price feedback loop.
Market objects are fast. They cannot prove a Claim or establish a causal edge.
"""

from __future__ import annotations

from typing import Any

from stock_pm.research.ids import new_id
from stock_pm.research.llm_reason import compact_text

from .types import MARKET_ALIGNMENTS


def normalize_market_attention(raw: dict[str, Any], *, ticker: str) -> dict[str, Any]:
    symbol = str(ticker or raw.get("ticker") or "").upper()
    statement = compact_text(raw.get("statement") or raw.get("name") or raw.get("reason") or "", 240)
    name = compact_text(raw.get("name") or statement or "market_attention", 80) or "market_attention"
    alignment = str(raw.get("alignment") or "unknown")
    if alignment not in MARKET_ALIGNMENTS:
        alignment = "unknown"
    related = [str(item) for item in (raw.get("related_objects") or []) if str(item).strip()]
    return {
        "attention_id": raw.get("attention_id") or new_id("batt"),
        "ticker": symbol,
        "name": name,
        "statement": statement,
        "object_id": raw.get("object_id") or "",
        "related_objects": related,
        "source_kind": str(raw.get("source_kind") or "news"),
        "alignment": alignment,
        "evidence_ids": [str(item) for item in (raw.get("evidence_ids") or []) if str(item).strip()],
        "reason": compact_text(raw.get("reason") or statement, 240),
    }


def event_has_tape(event: dict[str, Any] | None) -> bool:
    item = event or {}
    if str(item.get("kind") or item.get("source_kind") or "").lower() == "price":
        return True
    if item.get("price_reaction") or item.get("price_move"):
        return True
    change = item.get("price_change_pct")
    if change not in (None, "", 0, "0"):
        return True
    return False


def _hay(row: dict[str, Any] | None) -> str:
    item = row or {}
    return " ".join(
        str(item.get(key) or "")
        for key in ("name", "statement", "reason", "object_id")
    ).lower()


def relevant_market_attentions(
    *,
    event: dict[str, Any] | None,
    attentions: list[dict[str, Any]] | None,
    related_ids: set[str] | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    item = event or {}
    blob = f"{item.get('title') or ''} {item.get('fact') or ''} {' '.join(str(x) for x in (item.get('entities') or []))}".lower()
    wanted = {str(token).lower() for token in (related_ids or set()) if str(token).strip()}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in attentions or []:
        aid = str(row.get("attention_id") or row.get("name") or "")
        if not aid or aid in seen:
            continue
        text = _hay(row)
        related = {str(token).lower() for token in (row.get("related_objects") or []) if str(token)}
        hit = bool(related & wanted)
        if any(token in text for token in blob.split() if len(token) > 4):
            hit = True
        if wanted and str(row.get("object_id") or "").lower() in wanted:
            hit = True
        if hit or (not wanted and event_has_tape(item)):
            seen.add(aid)
            out.append(row)
        if len(out) >= limit:
            break
    return out[:limit]


def align_market_with_path(
    *,
    event: dict[str, Any] | None,
    attentions: list[dict[str, Any]] | None,
    transmission: dict[str, Any] | None,
    gaps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tape = event_has_tape(event) or bool(attentions)
    successful = int((transmission or {}).get("successful_count") or 0)
    blocked = int((transmission or {}).get("blocked_count") or 0)
    has_gap = bool(gaps)
    path_ok = successful > 0 and blocked == 0
    if not tape:
        return {
            "alignment": "unknown",
            "cannot_conclude_mispricing": True,
            "reason": "No tape evidence in this update.",
        }
    attention_text = " ".join(_hay(row) for row in (attentions or [])).lower()
    path_nodes = " ".join(
        " ".join(str(node) for node in (row.get("nodes") or []))
        for row in ((transmission or {}).get("successful") or [])
    ).lower()
    overlap = bool(attention_text and path_nodes and any(token in attention_text for token in path_nodes.split() if len(token) > 4))
    if path_ok and attentions and overlap:
        return {
            "alignment": "aligned",
            "cannot_conclude_mispricing": True,
            "reason": "Tape appears to be trading the same causal path. That does not rewrite Claims.",
        }
    if path_ok:
        return {
            "alignment": "partial",
            "cannot_conclude_mispricing": True,
            "reason": "A transmittable path exists and the tape moved; Claims stay unchanged.",
        }
    return {
        "alignment": "unexplained",
        "cannot_conclude_mispricing": True,
        "reason": "Price or attention moved without a transmittable Brain path. That is not mispricing."
        if (blocked or has_gap or not path_ok)
        else "Market attention is not a causal proof.",
    }
