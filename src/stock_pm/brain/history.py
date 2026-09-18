"""Brain object history so thesis changes can be reconstructed."""

from __future__ import annotations

from typing import Any

from stock_pm.research.ids import new_id
from stock_pm.research.llm_reason import compact_text


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
