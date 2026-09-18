"""FULL REVIEW vs INCREMENTAL UPDATE scoping."""

from __future__ import annotations

from typing import Any

FULL_TRIGGERS = (
    "earnings",
    "guidance",
    "mna",
    "regulation",
    "major_customer",
    "base_case",
    "periodic",
    "manual",
    "first_run",
    "structural",
)
FULL_EVENT_TYPES = ("earnings", "guidance", "mna", "regulation")


def should_full_review(
    *,
    prior_drivers: list[dict[str, Any]] | None = None,
    prior_claims: list[dict[str, Any]] | None = None,
    trigger: str | None = None,
    mode: str | None = None,
    event: dict[str, Any] | None = None,
) -> bool:
    if str(mode or "").lower() == "full":
        return True
    if not prior_drivers or not prior_claims:
        return True
    reason = full_review_reason(trigger=trigger, event=event, mode=mode)
    return reason is not None


def full_review_reason(
    *,
    trigger: str | None = None,
    event: dict[str, Any] | None = None,
    mode: str | None = None,
) -> str | None:
    if str(mode or "").lower() == "full":
        return "manual"
    token = str(trigger or "").lower()
    if token in FULL_TRIGGERS:
        return token
    item = event or {}
    event_type = str(item.get("event_type") or "").lower()
    if event_type in FULL_EVENT_TYPES:
        return event_type
    blob = f"{item.get('title') or ''} {item.get('fact') or ''} {item.get('statement') or ''}".lower()
    if any(word in blob for word in ("earnings", "10-q", "10-k", "quarterly results")):
        return "earnings"
    if "guidance" in blob:
        return "guidance"
    if any(word in blob for word in ("acquire", "merger", "m&a", "takeover")):
        return "mna"
    if any(word in blob for word in ("regulator", "doj", "antitrust", "ban")):
        return "regulation"
    return None


def critic_should_expand(
    *,
    proposals: list[dict[str, Any]] | None = None,
    budget: dict[str, Any] | None = None,
) -> bool:
    rows = [row for row in (proposals or []) if isinstance(row, dict)]
    claims = [row for row in rows if str(row.get("object_type") or "") in {"claim", "core_claim"}]
    bases = [
        row
        for row in rows
        if str(row.get("object_type") or "") == "scenario"
        and (
            (row.get("to_payload") or {}).get("base_case_change") is True
            or str((row.get("to_payload") or {}).get("scope") or "") == "base"
        )
    ]
    if len(claims) > 1 or bases:
        return True
    if (budget or {}).get("abnormal_change_scope"):
        return True
    return False


def affected_scope(
    *,
    events: list[dict[str, Any]],
    transmissions: list[dict[str, Any]],
    drivers: list[dict[str, Any]],
    claims: list[dict[str, Any]],
) -> dict[str, list[str]]:
    driver_ids: list[str] = []
    claim_ids: list[str] = []
    state_ids: list[str] = []
    for row in transmissions or []:
        for item in row.get("affected_drivers") or []:
            key = str(item)
            if key not in driver_ids:
                driver_ids.append(key)
        for item in row.get("affected_claims") or []:
            key = str(item)
            if key not in claim_ids:
                claim_ids.append(key)
        for item in row.get("affected_states") or []:
            key = str(item)
            if key not in state_ids:
                state_ids.append(key)
    for event in events or []:
        if str(event.get("materiality") or "") != "material":
            continue
        for item in event.get("affected_drivers") or []:
            if str(item) not in driver_ids:
                driver_ids.append(str(item))
        for item in event.get("affected_claims") or []:
            if str(item) not in claim_ids:
                claim_ids.append(str(item))
    if not driver_ids and not claim_ids:
        return {"drivers": [], "claims": [], "states": state_ids, "touched": False}
    return {"drivers": driver_ids, "claims": claim_ids, "states": state_ids, "touched": True}
