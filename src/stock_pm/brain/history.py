"""Brain object history so thesis changes can be reconstructed."""

from __future__ import annotations

from typing import Any

from stock_pm.research.ids import new_id
from stock_pm.research.llm_reason import compact_text

SKIP_HISTORY_KEYS = {
    "updated_at",
    "created_at",
    "last_reviewed_at",
    "run_id",
    "snapshot_id",
    "history_id",
    "match_action",
    "evidence_set_id",
}


def meaningful_delta(from_payload: dict[str, Any] | None, to_payload: dict[str, Any] | None) -> bool:
    before = dict(from_payload or {})
    after = dict(to_payload or {})
    keys = (set(before) | set(after)) - SKIP_HISTORY_KEYS
    if not keys:
        return bool(after) and not before
    return any(before.get(key) != after.get(key) for key in keys)


def history_row(
    *,
    ticker: str,
    object_type: str,
    object_id: str,
    from_payload: dict[str, Any] | None,
    to_payload: dict[str, Any] | None,
    reason: str,
    event_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    return {
        "history_id": new_id("bhis"),
        "ticker": str(ticker).upper(),
        "object_type": object_type,
        "object_id": object_id,
        "from_payload": dict(from_payload or {}),
        "to_payload": dict(to_payload or {}),
        "reason": compact_text(reason, 400),
        "event_id": event_id,
        "run_id": run_id,
    }


def record_history(
    store: Any,
    *,
    ticker: str,
    object_type: str,
    object_id: str,
    from_payload: dict[str, Any] | None,
    to_payload: dict[str, Any] | None,
    reason: str,
    event_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    if store is None or not hasattr(store, "insert_history"):
        return None
    if not meaningful_delta(from_payload, to_payload):
        return None
    return store.insert_history(
        history_row(
            ticker=ticker,
            object_type=object_type,
            object_id=object_id,
            from_payload=from_payload,
            to_payload=to_payload,
            reason=reason,
            event_id=event_id,
            run_id=run_id,
        )
    )


def persist_baseline_history(store: Any, ticker: str) -> None:
    """Record first Slow Brain objects so What Changed can read them after restart."""
    if store is None:
        return
    symbol = str(ticker or "").upper()

    def _rows(method: str) -> list[dict[str, Any]]:
        if not hasattr(store, method):
            return []
        return list(getattr(store, method)(symbol) or [])

    existing = {
        (str(row.get("object_type") or ""), str(row.get("object_id") or ""))
        for row in _rows("list_history")
    }
    states = _rows("list_current_states") or _rows("list_states")
    company = [
        row
        for row in states
        if str(row.get("state_type") or "company").lower() in {"company", "company_state"}
    ]
    for row in company or states:
        oid = str(row.get("state_id") or "")
        if not oid or ("company_state", oid) in existing or ("state", oid) in existing:
            continue
        record_history(
            store,
            ticker=symbol,
            object_type="company_state",
            object_id=oid,
            from_payload={},
            to_payload={"name": row.get("name"), "statement": row.get("statement"), "confidence": row.get("confidence")},
            reason="cold_start_baseline",
        )
    for row in _rows("list_drivers"):
        oid = str(row.get("driver_id") or "")
        if not oid or ("value_driver", oid) in existing or ("driver", oid) in existing:
            continue
        record_history(
            store,
            ticker=symbol,
            object_type="value_driver",
            object_id=oid,
            from_payload={},
            to_payload={"name": row.get("name"), "current_state": row.get("current_state"), "canonical_key": row.get("canonical_key")},
            reason="cold_start_baseline",
        )
    claims = [row for row in _rows("list_active_claims") if row.get("is_core")]
    for row in claims:
        oid = str(row.get("claim_id") or "")
        if not oid or ("core_claim", oid) in existing or ("claim", oid) in existing:
            continue
        record_history(
            store,
            ticker=symbol,
            object_type="core_claim",
            object_id=oid,
            from_payload={},
            to_payload={"title": row.get("title"), "statement": row.get("statement"), "status": row.get("status")},
            reason="cold_start_baseline",
        )


def why_thesis_changed(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timeline = sorted(rows or [], key=lambda item: str(item.get("created_at") or ""))
    out = []
    for row in timeline:
        out.append(
            {
                "history_id": row.get("history_id"),
                "object_type": row.get("object_type"),
                "object_id": row.get("object_id"),
                "event_id": row.get("event_id"),
                "reason": row.get("reason"),
                "from": row.get("from_payload") or {},
                "to": row.get("to_payload") or {},
                "created_at": row.get("created_at"),
            }
        )
    return out
