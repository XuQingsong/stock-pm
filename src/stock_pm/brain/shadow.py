"""Unconfirmed information hangs in Shadow State. It cannot pollute Current State."""

from __future__ import annotations

from typing import Any

from stock_pm.research.ids import new_id
from stock_pm.research.llm_reason import compact_text

from .knowledge import fact_reliability
from .limits import limit_words
from .types import CONFIDENCE, LOW_RELIABILITY, SHADOW_STATUSES


def should_enter_shadow(observation: dict[str, Any] | None) -> bool:
    item = observation or {}
    if str(item.get("shadow") or "").lower() in {"1", "true", "yes"}:
        return True
    if str(item.get("confirmed") or "").lower() in {"1", "true", "yes"}:
        return False
    reliability = str(item.get("fact_reliability") or fact_reliability(item))
    confidence = str(item.get("confidence") or "").lower()
    blob = f"{item.get('title') or ''} {item.get('fact') or ''} {item.get('statement') or ''}".lower()
    if reliability in LOW_RELIABILITY or confidence == "low":
        return True
    return any(token in blob for token in ("unconfirmed", "rumor", "reportedly", "possible", "may reduce", "might", "小作文"))


def normalize_shadow(raw: dict[str, Any], *, ticker: str) -> dict[str, Any]:
    confidence = str(raw.get("confidence") or "low")
    if confidence not in CONFIDENCE:
        confidence = "low"
    status = str(raw.get("status") or "open")
    if status not in SHADOW_STATUSES:
        status = "open"
    name = compact_text(raw.get("name") or raw.get("subject") or raw.get("title") or "", 80)
    return {
        "shadow_id": raw.get("shadow_id") or new_id("bshd"),
        "ticker": str(ticker).upper(),
        "name": name or "unconfirmed_signal",
        "statement": limit_words(compact_text(raw.get("statement") or raw.get("fact") or name, 400), 40),
        "confidence": confidence,
        "materiality_if_true": raw.get("materiality_if_true") or "high",
        "status": status,
        "evidence_ids": [str(item) for item in (raw.get("evidence_ids") or []) if str(item).strip()],
        "related_object_ids": [str(item) for item in (raw.get("related_object_ids") or []) if str(item).strip()],
        "source_kind": raw.get("source_kind") or raw.get("kind") or "signal",
    }


def shadow_blocks_current_state(shadow: dict[str, Any] | None) -> bool:
    status = str((shadow or {}).get("status") or "open")
    return status in {"open", "watching"}
