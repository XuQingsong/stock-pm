"""State layer: current world state with stable identity.

A state is not a Claim. Example: 'Hyperscaler AI capex accelerating' is industry state.
"""

from __future__ import annotations

import hashlib
from typing import Any

from stock_pm.research.ids import new_id
from stock_pm.research.llm_reason import compact_text

from .limits import limit_words
from .types import CONFIDENCE, STATE_TYPES


def _norm(value: Any) -> str:
    text = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or ""))
    return "_".join(part for part in text.split("_") if part)[:80] or "unspecified"


def make_state_key(ticker: str | None, state_type: str, subject: str) -> str:
    blob = "|".join([str(ticker or "").upper() or "GLOBAL", _norm(state_type), _norm(subject)])
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]
    return f"bsk_{digest}"


def normalize_state(
    raw: dict[str, Any],
    *,
    ticker: str | None,
    allowed_ids: set[str],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    subject = compact_text(raw.get("subject") or raw.get("name") or "", 80)
    if not subject:
        return None
    state_type = str(raw.get("state_type") or raw.get("type") or "company")
    if state_type not in STATE_TYPES:
        state_type = "company"
    evidence_ids = []
    for item in raw.get("evidence_ids") or []:
        key = str(item or "").strip()
        if key and key in allowed_ids and key not in evidence_ids:
            evidence_ids.append(key)
    confidence = str(raw.get("confidence") or "low")
    if confidence not in CONFIDENCE:
        confidence = "low"
    return {
        "state_id": (existing or {}).get("state_id") or raw.get("state_id") or new_id("bst"),
        "ticker": (str(ticker or "").upper() or None),
        "state_key": (existing or {}).get("state_key") or make_state_key(ticker, state_type, subject),
        "state_type": state_type,
        "subject": _norm(subject),
        "name": subject,
        "statement": limit_words(compact_text(raw.get("statement") or raw.get("qualitative_state") or "", 400), 40),
        "qualitative_state": limit_words(compact_text(raw.get("qualitative_state") or raw.get("current_value") or raw.get("statement") or "", 200), 24),
        "current_value": compact_text(raw.get("current_value") or "", 80) or None,
        "direction": compact_text(raw.get("direction") or "", 40) or None,
        "confidence": confidence,
        "effective_at": raw.get("effective_date") or raw.get("effective_at"),
        "evidence_ids": evidence_ids,
        "related_entities": [str(item) for item in (raw.get("related_entities") or raw.get("related_entity_ids") or []) if str(item).strip()],
        "source": raw.get("source") or "brain_state",
        "match_action": "update_existing" if existing else "create_new",
    }


def match_existing_state(item: dict[str, Any], existing: list[dict[str, Any]]) -> dict[str, Any] | None:
    key = str(item.get("state_key") or "")
    subject = str(item.get("subject") or "")
    state_type = str(item.get("state_type") or "")
    for row in existing or []:
        if key and row.get("state_key") == key:
            return row
        if row.get("subject") == subject and row.get("state_type") == state_type:
            return row
        if row.get("name") == item.get("name") and row.get("state_type") == state_type:
            return row
    return None
