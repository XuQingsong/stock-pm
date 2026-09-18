"""Core Claims are slow variables. One news item cannot flip status."""

from __future__ import annotations

from typing import Any

from .types import CLAIM_STATUS_RANK, CLAIM_STATUSES


def _rank(status: Any) -> int:
    return CLAIM_STATUS_RANK.get(str(status or ""), 2)


def accumulate_claim_evidence(claim: dict[str, Any] | None, *, direction: str, strength: str = "medium") -> dict[str, Any]:
    row = dict(claim or {})
    bump = 2 if strength == "strong" else 1 if strength == "medium" else 0
    if direction == "oppose":
        row["counter_strength"] = int(row.get("counter_strength") or 0) + bump
        row["counter_trend"] = "up"
        row["support_trend"] = "flat"
    else:
        row["support_strength"] = int(row.get("support_strength") or 0) + bump
        row["support_trend"] = "up"
        row["counter_trend"] = "flat"
    row["last_material_change"] = row.get("last_material_change")
    return row


def next_claim_status(
    current: dict[str, Any] | None,
    proposed_status: str | None,
    *,
    independent_counter_count: int = 0,
    source_kind: str | None = None,
) -> dict[str, Any]:
    now = str((current or {}).get("status") or "emerging")
    want = str(proposed_status or now)
    if want not in CLAIM_STATUSES:
        want = now
    current_rank = _rank(now)
    want_rank = _rank(want)
    delta = want_rank - current_rank
    news_like = str(source_kind or "") in {"news", "event", "price", "signal", "rumor"}
    if news_like and abs(delta) >= 1 and independent_counter_count < 2:
        return {
            "status": now,
            "changed": False,
            "reason": "claim_hysteresis_single_item",
            "support_strength": int((current or {}).get("support_strength") or 0),
            "counter_strength": int((current or {}).get("counter_strength") or 0),
        }
    if abs(delta) > 1:
        stepped = current_rank + (1 if delta > 0 else -1)
        status = next((key for key, rank in CLAIM_STATUS_RANK.items() if rank == stepped), now)
        return {"status": status, "changed": status != now, "reason": "claim_hysteresis_one_step"}
    return {"status": want, "changed": want != now, "reason": "claim_status_allowed"}
